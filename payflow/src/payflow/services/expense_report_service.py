"""Expense reports: draft → submit → approve/reject → reimburse (Phase 3).

PF-009: approver may be submitter (no self-approval check).
PF-010: bulk action always HTTP 200 at router (service returns payload only).
PF-011: multi-level uses strict `>` vs threshold (not `>=`).
"""

from __future__ import annotations

import uuid
from typing import Any

import aiosqlite

from payflow.config import get_settings
from payflow.exceptions import AppError
from payflow.database import fetch_all, fetch_one, transaction_immediate
from payflow.services.transfer_service import transfer_funds_atomic
from payflow.utils.currency import paise_to_sim, sim_to_paise
from payflow.utils.pagination import build_meta, offset_for_page

# Line items strictly above 500.00 SIM require receipt_url (500.00 SIM = 50000 paise)
RECEIPT_REQUIRED_ABOVE_PAISE = 50_000

DEFAULT_MULTI_LEVEL_THRESHOLD_PAISE = 5_000_000  # 50000.00 SIM


def _parse_report_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "submitter_id": row["submitter_id"],
        "title": row["title"],
        "status": row["status"],
        "total_amount": paise_to_sim(int(row["total_amount"])),
        "currency": row["currency"],
        "submitted_at": row["submitted_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "rejection_reason": row["rejection_reason"],
        "requires_multi_level": bool(row["requires_multi_level"]),
        "multi_level_threshold": paise_to_sim(int(row["multi_level_threshold"])),
        "second_reviewer_id": row["second_reviewer_id"],
        "second_reviewed_at": row["second_reviewed_at"],
        "reimbursement_transaction_id": row["reimbursement_transaction_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _line_items_for_report(
    conn: aiosqlite.Connection, report_id: str
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT li.*, ec.name AS category_name
        FROM expense_line_items li
        JOIN expense_categories ec ON ec.id = li.category_id
        WHERE li.expense_report_id = ?
        ORDER BY li.created_at
        """,
        (report_id,),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "description": r["description"],
                "amount": paise_to_sim(int(r["amount"])),
                "receipt_url": r["receipt_url"],
                "date": r["date"],
                "created_at": r["created_at"],
            }
        )
    return out


async def _get_submitter_sim_wallet(
    conn: aiosqlite.Connection, user_id: str
) -> aiosqlite.Row:
    w = await fetch_one(
        conn,
        """
        SELECT * FROM wallets
        WHERE user_id = ? AND currency = 'SIM' AND status = 'active'
        LIMIT 1
        """,
        (user_id,),
    )
    if w is None:
        raise AppError(
            "INVALID_STATE",
            "Submitter has no active SIM wallet for reimbursement",
            status_code=422,
        )
    return w


async def create_report(
    conn: aiosqlite.Connection,
    *,
    submitter_id: str,
    title: str,
    line_items: list[dict[str, Any]],
) -> dict[str, Any]:
    rid = str(uuid.uuid4())
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    total_paise = 0
    validated_lines: list[tuple[dict[str, Any], int, aiosqlite.Row]] = []

    for li in line_items:
        try:
            amt = sim_to_paise(li["amount"])
        except ValueError as e:
            raise AppError(
                "VALIDATION_ERROR", "Invalid line item amount", status_code=400
            ) from e
        if amt <= 0:
            raise AppError("VALIDATION_ERROR", "Line amount must be > 0", status_code=400)

        cat = await fetch_one(
            conn,
            "SELECT * FROM expense_categories WHERE id = ? AND is_active = 1",
            (li["category_id"],),
        )
        if cat is None:
            raise AppError(
                "VALIDATION_ERROR",
                "Unknown or inactive expense category",
                status_code=400,
                details={"category_id": li["category_id"]},
            )
        plimit = cat["policy_limit"]
        if plimit is not None and amt > int(plimit):
            raise AppError(
                "VALIDATION_ERROR",
                "Line amount exceeds category policy limit",
                status_code=400,
                details={"category_id": li["category_id"]},
            )

        # Receipt required for amounts strictly greater than 500.00 SIM
        if amt > RECEIPT_REQUIRED_ABOVE_PAISE:
            ru = li.get("receipt_url")
            if not ru or not str(ru).strip():
                raise AppError(
                    "VALIDATION_ERROR",
                    "receipt_url required for line amounts over 500.00 SIM",
                    status_code=400,
                )

        validated_lines.append((li, amt, cat))
        total_paise += amt

    await conn.execute(
        """
        INSERT INTO expense_reports (
            id, submitter_id, title, status, total_amount, currency,
            requires_multi_level, multi_level_threshold, created_at, updated_at
        ) VALUES (?, ?, ?, 'draft', ?, 'SIM', 0, ?, ?, ?)
        """,
        (
            rid,
            submitter_id,
            title,
            total_paise,
            DEFAULT_MULTI_LEVEL_THRESHOLD_PAISE,
            ts,
            ts,
        ),
    )

    for li, amt, _cat in validated_lines:
        lid = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO expense_line_items (
                id, expense_report_id, category_id, description, amount, receipt_url, date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lid,
                rid,
                li["category_id"],
                li["description"].strip(),
                amt,
                li.get("receipt_url"),
                li["date"],
                ts,
            ),
        )

    row = await fetch_one(conn, "SELECT * FROM expense_reports WHERE id = ?", (rid,))
    assert row is not None
    data = _parse_report_row(row)
    data["line_items"] = await _line_items_for_report(conn, rid)
    return data


async def submit_report(
    conn: aiosqlite.Connection, *, report_id: str, user_id: str
) -> dict[str, Any]:
    row = await fetch_one(
        conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    )
    if row is None:
        raise AppError("NOT_FOUND", "Expense report not found", status_code=404)
    if row["submitter_id"] != user_id:
        raise AppError("FORBIDDEN", "Only the submitter can submit this report", status_code=403)
    if row["status"] != "draft":
        raise AppError(
            "INVALID_STATE", "Only draft reports can be submitted", status_code=422
        )

    cnt = await fetch_one(
        conn,
        "SELECT COUNT(*) AS c FROM expense_line_items WHERE expense_report_id = ?",
        (report_id,),
    )
    assert cnt is not None
    if int(cnt["c"]) < 1:
        raise AppError(
            "VALIDATION_ERROR",
            "Report must have at least one line item to submit",
            status_code=400,
        )

    total = int(row["total_amount"])
    threshold = int(row["multi_level_threshold"])
    # PF-011: strict greater-than (exact threshold does NOT require multi-level)
    requires_multi = 1 if total > threshold else 0

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    await conn.execute(
        """
        UPDATE expense_reports SET
          status = 'submitted',
          submitted_at = ?,
          requires_multi_level = ?,
          updated_at = ?
        WHERE id = ?
        """,
        (ts, requires_multi, ts, report_id),
    )

    out = await fetch_one(conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,))
    assert out is not None
    data = _parse_report_row(out)
    data["line_items"] = await _line_items_for_report(conn, report_id)
    return data


async def _finalize_reimburse(
    conn: aiosqlite.Connection,
    report: aiosqlite.Row,
    *,
    second_reviewer: bool,
    approver_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    source_wid = settings.reimbursement_wallet_id.strip()
    submitter_id = report["submitter_id"]
    total_paise = int(report["total_amount"])
    rid = report["id"]

    dest = await _get_submitter_sim_wallet(conn, submitter_id)

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    xfer = await transfer_funds_atomic(
        conn,
        sender_wallet_id=source_wid,
        receiver_wallet_id=dest["id"],
        amount_paise=total_paise,
        description=f"Expense reimbursement {rid}",
        reference_type="expense_report",
        reference_id=rid,
    )

    if second_reviewer:
        await conn.execute(
            """
            UPDATE expense_reports SET
              status = 'reimbursed',
              second_reviewer_id = ?,
              second_reviewed_at = ?,
              reimbursement_transaction_id = ?,
              updated_at = ?
            WHERE id = ?
            """,
            (approver_id, ts, xfer["transaction_id"], ts, rid),
        )
    else:
        await conn.execute(
            """
            UPDATE expense_reports SET
              status = 'reimbursed',
              reviewed_by = ?,
              reviewed_at = ?,
              reimbursement_transaction_id = ?,
              updated_at = ?
            WHERE id = ?
            """,
            (approver_id, ts, xfer["transaction_id"], ts, rid),
        )

    out = await fetch_one(conn, "SELECT * FROM expense_reports WHERE id = ?", (rid,))
    assert out is not None
    data = _parse_report_row(out)
    data["line_items"] = await _line_items_for_report(conn, rid)
    data["reimbursement"] = xfer
    return data


async def approve_report(
    conn: aiosqlite.Connection,
    *,
    report_id: str,
    approver_id: str,
    approver_role: str,
    notes: str | None,
) -> dict[str, Any]:
    if approver_role not in ("manager", "admin"):
        raise AppError(
            "FORBIDDEN",
            "Only managers or admins can approve expense reports",
            status_code=403,
        )

    row = await fetch_one(
        conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    )
    if row is None:
        raise AppError("NOT_FOUND", "Expense report not found", status_code=404)

    # PF-009: intentionally no check that approver_id != submitter_id

    st = row["status"]
    if st not in ("submitted", "under_review"):
        raise AppError(
            "INVALID_STATE",
            "Report is not awaiting approval",
            status_code=422,
        )

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    if st == "submitted":
        if int(row["requires_multi_level"]) == 1:
            await conn.execute(
                """
                UPDATE expense_reports SET
                  status = 'under_review',
                  reviewed_by = ?,
                  reviewed_at = ?,
                  updated_at = ?
                WHERE id = ?
                """,
                (approver_id, ts, ts, report_id),
            )
            out = await fetch_one(
                conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
            )
            assert out is not None
            data = _parse_report_row(out)
            data["line_items"] = await _line_items_for_report(conn, report_id)
            data["notes"] = notes
            return data

        return await _finalize_reimburse(conn, row, second_reviewer=False, approver_id=approver_id)

    # under_review → final approval
    return await _finalize_reimburse(conn, row, second_reviewer=True, approver_id=approver_id)


async def reject_report(
    conn: aiosqlite.Connection,
    *,
    report_id: str,
    actor_id: str,
    actor_role: str,
    reason: str,
) -> dict[str, Any]:
    if actor_role not in ("manager", "admin"):
        raise AppError(
            "FORBIDDEN",
            "Only managers or admins can reject expense reports",
            status_code=403,
        )

    row = await fetch_one(
        conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    )
    if row is None:
        raise AppError("NOT_FOUND", "Expense report not found", status_code=404)

    if row["status"] not in ("submitted", "under_review"):
        raise AppError(
            "INVALID_STATE",
            "Report cannot be rejected in its current state",
            status_code=422,
        )

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    await conn.execute(
        """
        UPDATE expense_reports SET
          status = 'rejected',
          rejection_reason = ?,
          reviewed_by = ?,
          reviewed_at = ?,
          updated_at = ?
        WHERE id = ?
        """,
        (reason.strip(), actor_id, ts, ts, report_id),
    )

    out = await fetch_one(conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,))
    assert out is not None
    data = _parse_report_row(out)
    data["line_items"] = await _line_items_for_report(conn, report_id)
    return data


async def bulk_action(
    *,
    actor_id: str,
    actor_role: str,
    action: str,
    report_ids: list[str],
    notes: str | None,
    reason: str | None,
) -> dict[str, Any]:
    """Each report is processed in its own transaction (partial success possible)."""
    results: list[dict[str, Any]] = []
    if action == "reject" and (not reason or not str(reason).strip()):
        raise AppError(
            "VALIDATION_ERROR",
            "reason is required for bulk reject",
            status_code=400,
        )

    for rid in report_ids:
        try:
            async with transaction_immediate() as conn:
                if action == "approve":
                    data = await approve_report(
                        conn,
                        report_id=rid,
                        approver_id=actor_id,
                        approver_role=actor_role,
                        notes=notes,
                    )
                else:
                    data = await reject_report(
                        conn,
                        report_id=rid,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        reason=reason or "",
                    )
            results.append({"id": rid, "status": "success", "data": data})
        except AppError as e:
            results.append(
                {
                    "id": rid,
                    "status": "failed",
                    "error": {"code": e.code, "message": e.message},
                }
            )
    return {"results": results}


async def get_report(
    conn: aiosqlite.Connection,
    *,
    report_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    row = await fetch_one(
        conn, "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    )
    if row is None:
        raise AppError("NOT_FOUND", "Expense report not found", status_code=404)
    if row["submitter_id"] != actor_id and actor_role not in ("manager", "admin"):
        raise AppError("FORBIDDEN", "Cannot view this report", status_code=403)
    data = _parse_report_row(row)
    data["line_items"] = await _line_items_for_report(conn, report_id)
    return data


async def list_reports(
    conn: aiosqlite.Connection,
    *,
    actor_id: str,
    actor_role: str,
    page: int,
    limit: int,
    status: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    off = offset_for_page(page, limit)
    where_parts: list[str] = []
    count_params: list[Any] = []

    if actor_role in ("manager", "admin"):
        if status:
            where_parts.append("status = ?")
            count_params.append(status)
    else:
        where_parts.append("submitter_id = ?")
        count_params.append(actor_id)
        if status:
            where_parts.append("status = ?")
            count_params.append(status)

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    total_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM expense_reports WHERE {where_sql}",
        tuple(count_params),
    )
    total = int(total_row["c"]) if total_row else 0

    list_params = list(count_params)
    list_params.extend([limit, off])
    rows = await fetch_all(
        conn,
        f"""
        SELECT * FROM expense_reports
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(list_params),
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        d = _parse_report_row(r)
        d["line_items"] = await _line_items_for_report(conn, r["id"])
        out.append(d)

    meta = build_meta(page=page, limit=limit, total=total)
    return out, meta


async def list_categories(
    conn: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        "SELECT * FROM expense_categories WHERE is_active = 1 ORDER BY name",
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "policy_limit": paise_to_sim(int(r["policy_limit"]))
            if r["policy_limit"] is not None
            else None,
            "is_active": bool(r["is_active"]),
        }
        for r in rows
    ]
