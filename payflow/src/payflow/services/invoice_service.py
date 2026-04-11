"""Invoices (Phase 4). PF-014: due date from full datetime without date-only normalization."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.services import exchange_rate_service
from payflow.utils.currency import paise_to_sim, sim_to_paise
from payflow.utils.pagination import build_meta, offset_for_page

_DAYS = {"immediate": 0, "net_15": 15, "net_30": 30, "net_60": 60}


def _due_date_pf014(created_at_sql: str, payment_terms: str) -> str:
    """PF-014: add days to full timestamp, then take date (buggy vs calendar add to date only)."""
    days = _DAYS.get(payment_terms, 30)
    try:
        dt = datetime.strptime(created_at_sql[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.strptime(created_at_sql[:10], "%Y-%m-%d")
    due = dt + timedelta(days=days)
    return due.strftime("%Y-%m-%d")


async def create_invoice(
    conn: aiosqlite.Connection,
    *,
    actor_user_id: str,
    vendor_id: str,
    invoice_number: str,
    amount_str: str,
    currency: str,
    description: str | None,
    payer_wallet_id: str,
) -> dict[str, Any]:
    try:
        amount_paise = sim_to_paise(amount_str)
    except ValueError as e:
        raise AppError("VALIDATION_ERROR", "Invalid amount", status_code=400) from e
    if amount_paise <= 0:
        raise AppError("VALIDATION_ERROR", "Amount must be > 0", status_code=400)

    v = await fetch_one(
        conn,
        "SELECT * FROM vendors WHERE id = ? AND status = 'active'",
        (vendor_id,),
    )
    if v is None:
        raise AppError("NOT_FOUND", "Vendor not found or inactive", status_code=404)

    pw = await fetch_one(conn, "SELECT * FROM wallets WHERE id = ?", (payer_wallet_id,))
    if pw is None:
        raise AppError("NOT_FOUND", "Payer wallet not found", status_code=404)
    if pw["user_id"] != actor_user_id:
        raise AppError("FORBIDDEN", "Payer wallet must belong to you", status_code=403)

    dup = await fetch_one(
        conn, "SELECT id FROM invoices WHERE invoice_number = ?", (invoice_number,)
    )
    if dup:
        raise AppError("CONFLICT", "invoice_number already exists", status_code=409)

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    created_ts = now_row["t"]
    due_date = _due_date_pf014(created_ts, v["payment_terms"])

    rate = await exchange_rate_service.get_latest_rate(conn, currency, "SIM")
    meta = {"exchange_rate_at_creation": rate}

    iid = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO invoices (
            id, vendor_id, invoice_number, amount, currency, description,
            due_date, status, payer_wallet_id, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            iid,
            vendor_id,
            invoice_number,
            amount_paise,
            currency,
            description,
            due_date,
            payer_wallet_id,
            json.dumps(meta),
            created_ts,
            created_ts,
        ),
    )
    return await get_invoice(conn, iid)


async def approve_invoice(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
    invoice_id: str,
) -> dict[str, Any]:
    if actor_role not in ("admin", "manager"):
        raise AppError("FORBIDDEN", "Only admin or manager can approve invoices", status_code=403)

    inv = await fetch_one(conn, "SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if inv is None:
        raise AppError("NOT_FOUND", "Invoice not found", status_code=404)
    if inv["status"] != "pending":
        raise AppError("INVALID_STATE", "Only pending invoices can be approved", status_code=422)

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]
    await conn.execute(
        "UPDATE invoices SET status = 'approved', updated_at = ? WHERE id = ?",
        (ts, invoice_id),
    )
    return await get_invoice(conn, invoice_id)


async def get_invoice(conn: aiosqlite.Connection, invoice_id: str) -> dict[str, Any]:
    row = await fetch_one(conn, "SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if row is None:
        raise AppError("NOT_FOUND", "Invoice not found", status_code=404)
    return _invoice_dict(row)


def _invoice_dict(row: aiosqlite.Row) -> dict[str, Any]:
    meta = json.loads(row["metadata_json"] or "{}")
    return {
        "id": row["id"],
        "vendor_id": row["vendor_id"],
        "invoice_number": row["invoice_number"],
        "amount": paise_to_sim(int(row["amount"])),
        "currency": row["currency"],
        "description": row["description"],
        "due_date": row["due_date"],
        "status": row["status"],
        "payer_wallet_id": row["payer_wallet_id"],
        "transaction_id": row["transaction_id"],
        "batch_id": row["batch_id"],
        "metadata": meta,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_invoices(
    conn: aiosqlite.Connection,
    *,
    actor_user_id: str,
    actor_role: str,
    page: int,
    limit: int,
    status: str | None,
) -> tuple[list[dict[str, Any]], Any]:
    off = offset_for_page(page, limit)
    params: list[Any] = []
    if actor_role in ("admin", "manager"):
        where = "1=1"
    else:
        where = "payer_wallet_id IN (SELECT id FROM wallets WHERE user_id = ?)"
        params.append(actor_user_id)
    if status:
        where += " AND status = ?"
        params.append(status)

    total_row = await fetch_one(
        conn, f"SELECT COUNT(*) AS c FROM invoices WHERE {where}", tuple(params)
    )
    total = int(total_row["c"]) if total_row else 0

    qparams = list(params) + [limit, off]
    rows = await fetch_all(
        conn,
        f"SELECT * FROM invoices WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(qparams),
    )
    return [_invoice_dict(r) for r in rows], build_meta(page=page, limit=limit, total=total)
