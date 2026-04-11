"""Payment batch execution and settlements (Phase 4).

PF-013: settlement uses current batch exchange rate for aggregated settled_amount.
PF-015: vendor fetch requires active status; deleted vendors yield None and crash on wallet_id.
PF-016: CSV export without quoting fields (breaks on commas in vendor name).
"""

from __future__ import annotations

import io
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.services import exchange_rate_service
from payflow.services.transfer_service import transfer_funds_atomic
from payflow.utils.currency import paise_to_sim
from payflow.utils.pagination import build_meta, offset_for_page


async def execute_batch(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
) -> dict[str, Any]:
    if actor_role != "admin":
        raise AppError("FORBIDDEN", "Only admins can execute payment batches", status_code=403)
    return await _execute_batch_core(conn)


async def execute_batch_worker(conn: aiosqlite.Connection) -> dict[str, Any]:
    """Same as HTTP execute, without role check (background worker)."""
    return await _execute_batch_core(conn)


async def _execute_batch_core(conn: aiosqlite.Connection) -> dict[str, Any]:
    today = date.today().isoformat()
    inv_rows = await fetch_all(
        conn,
        """
        SELECT * FROM invoices
        WHERE status = 'approved' AND due_date <= ?
        ORDER BY vendor_id, id
        """,
        (today,),
    )
    if not inv_rows:
        return {"batch_id": None, "processed": 0, "failed": 0, "message": "No due approved invoices"}

    batch_id = str(uuid.uuid4())
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    await conn.execute(
        """
        INSERT INTO payment_batches (
            id, status, total_amount, total_invoices, processed_count, failed_count, created_at
        ) VALUES (?, 'processing', 0, ?, 0, 0, ?)
        """,
        (batch_id, len(inv_rows), ts),
    )

    processed = 0
    failed = 0
    total_paise = 0
    paid_by_vendor: dict[str, list[aiosqlite.Row]] = defaultdict(list)

    for inv in inv_rows:
        vendor = await fetch_one(
            conn,
            "SELECT * FROM vendors WHERE id = ? AND status = 'active'",
            (inv["vendor_id"],),
        )
        # PF-015: deleted vendor → None → TypeError (unhandled if not caught by caller)
        receiver_wid = vendor["wallet_id"]

        try:
            xfer = await transfer_funds_atomic(
                conn,
                sender_wallet_id=inv["payer_wallet_id"],
                receiver_wallet_id=receiver_wid,
                amount_paise=int(inv["amount"]),
                description=f"Invoice {inv['invoice_number']}",
                reference_type="invoice_payment",
                reference_id=inv["id"],
            )
        except AppError:
            failed += 1
            continue

        await conn.execute(
            """
            UPDATE invoices SET
              status = 'paid',
              transaction_id = ?,
              batch_id = ?,
              updated_at = ?
            WHERE id = ?
            """,
            (xfer["transaction_id"], batch_id, ts, inv["id"]),
        )
        total_paise += int(inv["amount"])
        processed += 1
        paid_by_vendor[inv["vendor_id"]].append(inv)

    current_rate = await exchange_rate_service.get_latest_rate(conn, "SIM", "SIM")

    for vendor_id, invs in paid_by_vendor.items():
        sum_orig = sum(int(i["amount"]) for i in invs)
        # PF-013: single current rate applied to aggregate (not per-invoice creation rates)
        settled_buggy = int(sum_orig * current_rate)
        await conn.execute(
            """
            INSERT INTO settlements (
                id, batch_id, vendor_id, total_amount, currency, exchange_rate_used, settled_amount, settled_at
            ) VALUES (?, ?, ?, ?, 'SIM', ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                batch_id,
                vendor_id,
                sum_orig,
                current_rate,
                settled_buggy,
                ts,
            ),
        )

    await conn.execute(
        """
        UPDATE payment_batches SET
          status = 'completed',
          total_amount = ?,
          processed_count = ?,
          failed_count = ?,
          executed_at = ?
        WHERE id = ?
        """,
        (total_paise, processed, failed, ts, batch_id),
    )

    return {
        "batch_id": batch_id,
        "processed": processed,
        "failed": failed,
        "total_amount": paise_to_sim(total_paise) if total_paise else "0.00",
    }


async def list_settlements(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
    date_from: str | None,
    date_to: str | None,
    vendor_id: str | None,
    page: int,
    limit: int,
    format_: str,
) -> tuple[Any, str | None]:
    if actor_role not in ("admin", "manager"):
        raise AppError("FORBIDDEN", "Insufficient permissions", status_code=403)

    params: list[Any] = []
    where = "1=1"
    if date_from:
        where += " AND s.settled_at >= ?"
        params.append(date_from)
    if date_to:
        where += " AND s.settled_at <= ?"
        params.append(date_to + "T23:59:59")
    if vendor_id:
        where += " AND s.vendor_id = ?"
        params.append(vendor_id)

    off = offset_for_page(page, limit)
    count_sql = f"""
        SELECT COUNT(*) AS c FROM settlements s
        JOIN vendors v ON v.id = s.vendor_id
        WHERE {where}
    """
    total_row = await fetch_one(conn, count_sql, tuple(params))
    total = int(total_row["c"]) if total_row else 0

    rows = await fetch_all(
        conn,
        f"""
        SELECT s.*, v.name AS vendor_name
        FROM settlements s
        JOIN vendors v ON v.id = s.vendor_id
        WHERE {where}
        ORDER BY s.settled_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [limit, off]),
    )

    data = [
        {
            "id": r["id"],
            "batch_id": r["batch_id"],
            "vendor_id": r["vendor_id"],
            "vendor_name": r["vendor_name"],
            "total_amount": paise_to_sim(int(r["total_amount"])),
            "currency": r["currency"],
            "exchange_rate_used": r["exchange_rate_used"],
            "settled_amount": paise_to_sim(int(r["settled_amount"])),
            "settled_at": r["settled_at"],
        }
        for r in rows
    ]

    meta = build_meta(page=page, limit=limit, total=total)

    if format_ == "csv":
        # PF-016: unquoted fields — commas in vendor_name break CSV
        buf = io.StringIO()
        buf.write("vendor_name,total_amount,currency,settled_amount,settled_at\n")
        for item in data:
            line = f"{item['vendor_name']},{item['total_amount']},{item['currency']},{item['settled_amount']},{item['settled_at']}\n"
            buf.write(line)
        return buf.getvalue(), "text/csv"

    return {"data": data, "meta": meta}, None
