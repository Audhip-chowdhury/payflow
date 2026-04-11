"""Scheduled one-off payments."""

from __future__ import annotations

import uuid
from datetime import date

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.utils.currency import sim_to_paise
from payflow.utils.pagination import build_meta, offset_for_page


def _today_iso() -> str:
    return date.today().isoformat()


async def create_scheduled(
    conn: aiosqlite.Connection,
    *,
    user_id: str,
    sender_wallet_id: str,
    receiver_wallet_id: str,
    amount_str: str,
    scheduled_date_str: str,
    description: str | None,
) -> dict:
    try:
        scheduled_date = date.fromisoformat(scheduled_date_str)
    except ValueError as e:
        raise AppError(
            "VALIDATION_ERROR",
            "scheduled_date must be YYYY-MM-DD",
            status_code=400,
        ) from e
    if scheduled_date < date.today():
        raise AppError(
            "VALIDATION_ERROR",
            "scheduled_date must be today or in the future",
            status_code=400,
        )

    try:
        amount_paise = sim_to_paise(amount_str)
    except ValueError as e:
        raise AppError("VALIDATION_ERROR", "Invalid amount", status_code=400) from e
    if amount_paise <= 0:
        raise AppError("VALIDATION_ERROR", "Amount must be > 0", status_code=400)

    sender = await fetch_one(
        conn,
        "SELECT * FROM wallets WHERE id = ?",
        (sender_wallet_id,),
    )
    if sender is None:
        raise AppError("NOT_FOUND", "Sender wallet not found", status_code=404)
    if sender["user_id"] != user_id:
        raise AppError("FORBIDDEN", "You do not own the sender wallet", status_code=403)

    recv = await fetch_one(
        conn,
        "SELECT id FROM wallets WHERE id = ?",
        (receiver_wallet_id,),
    )
    if recv is None:
        raise AppError("NOT_FOUND", "Receiver wallet not found", status_code=404)

    sid = str(uuid.uuid4())
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]
    await conn.execute(
        """
        INSERT INTO scheduled_payments (
            id, sender_wallet_id, receiver_wallet_id, amount, currency, description,
            scheduled_date, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            sid,
            sender_wallet_id,
            receiver_wallet_id,
            amount_paise,
            sender["currency"],
            description,
            scheduled_date.isoformat(),
            ts,
            ts,
        ),
    )
    return await get_scheduled_by_id(conn, sid)


async def get_scheduled_by_id(conn: aiosqlite.Connection, sid: str) -> dict:
    row = await fetch_one(
        conn,
        "SELECT * FROM scheduled_payments WHERE id = ?",
        (sid,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Scheduled payment not found", status_code=404)
    return _row_to_dict(row)


def _row_to_dict(row: aiosqlite.Row) -> dict:
    from payflow.utils.currency import paise_to_sim

    return {
        "id": row["id"],
        "sender_wallet_id": row["sender_wallet_id"],
        "receiver_wallet_id": row["receiver_wallet_id"],
        "amount": paise_to_sim(int(row["amount"])),
        "currency": row["currency"],
        "description": row["description"],
        "scheduled_date": row["scheduled_date"],
        "status": row["status"],
        "executed_at": row["executed_at"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_scheduled(
    conn: aiosqlite.Connection,
    *,
    actor_user_id: str,
    actor_role: str,
    status: str | None,
    wallet_id: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict], object]:
    """Default status filter: pending when omitted."""
    effective_status = status if status is not None else "pending"

    conds: list[str] = []
    params: list = []

    if wallet_id:
        conds.append("(sender_wallet_id = ? OR receiver_wallet_id = ?)")
        params.extend([wallet_id, wallet_id])
        if actor_role != "admin":
            own = await fetch_one(
                conn,
                "SELECT user_id FROM wallets WHERE id = ?",
                (wallet_id,),
            )
            if own is None or (
                own["user_id"] != actor_user_id
            ):
                raise AppError("FORBIDDEN", "Cannot list for this wallet", status_code=403)
    elif actor_role != "admin":
        conds.append(
            "sender_wallet_id IN (SELECT id FROM wallets WHERE user_id = ?)"
        )
        params.append(actor_user_id)

    conds.append("status = ?")
    params.append(effective_status)

    where = " AND ".join(conds)

    count_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM scheduled_payments WHERE {where}",
        tuple(params),
    )
    assert count_row is not None
    total = int(count_row["c"])

    off = offset_for_page(page, limit)
    params2 = list(params) + [limit, off]
    rows = await fetch_all(
        conn,
        f"""
        SELECT * FROM scheduled_payments WHERE {where}
        ORDER BY scheduled_date ASC, created_at ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params2),
    )
    meta = build_meta(page=page, limit=limit, total=total)
    return [_row_to_dict(r) for r in rows], meta


async def cancel_scheduled(
    conn: aiosqlite.Connection,
    *,
    schedule_id: str,
    actor_user_id: str,
    actor_role: str,
) -> dict:
    row = await fetch_one(
        conn,
        "SELECT * FROM scheduled_payments WHERE id = ?",
        (schedule_id,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Scheduled payment not found", status_code=404)
    if row["status"] != "pending":
        raise AppError(
            "INVALID_STATE",
            "Only pending scheduled payments can be cancelled",
            status_code=422,
        )
    sender = await fetch_one(
        conn,
        "SELECT user_id FROM wallets WHERE id = ?",
        (row["sender_wallet_id"],),
    )
    assert sender is not None
    if actor_role != "admin" and sender["user_id"] != actor_user_id:
        raise AppError("FORBIDDEN", "Only the sender or admin can cancel", status_code=403)

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]
    await conn.execute(
        """
        UPDATE scheduled_payments SET status = 'cancelled', updated_at = ? WHERE id = ?
        """,
        (ts, schedule_id),
    )
    return await get_scheduled_by_id(conn, schedule_id)
