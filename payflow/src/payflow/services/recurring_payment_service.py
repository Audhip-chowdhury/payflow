"""Recurring payment schedules."""

from __future__ import annotations

import uuid
from datetime import date

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.services import scheduler_service
from payflow.utils.currency import paise_to_sim, sim_to_paise
from payflow.utils.pagination import build_meta, offset_for_page


async def create_recurring(
    conn: aiosqlite.Connection,
    *,
    user_id: str,
    sender_wallet_id: str,
    receiver_wallet_id: str,
    amount_str: str,
    frequency: str,
    day_of_month: int | None,
    day_of_week: int | None,
    start_date_str: str,
    end_date_str: str | None,
    description: str | None,
) -> dict:
    try:
        start_date = date.fromisoformat(start_date_str)
    except ValueError as e:
        raise AppError(
            "VALIDATION_ERROR",
            "start_date must be YYYY-MM-DD",
            status_code=400,
        ) from e
    if start_date < date.today():
        raise AppError(
            "VALIDATION_ERROR",
            "start_date must be today or in the future",
            status_code=400,
        )

    end_date: date | None = None
    if end_date_str:
        try:
            end_date = date.fromisoformat(end_date_str)
        except ValueError as e:
            raise AppError(
                "VALIDATION_ERROR",
                "end_date must be YYYY-MM-DD",
                status_code=400,
            ) from e
        if end_date <= start_date:
            raise AppError(
                "VALIDATION_ERROR",
                "end_date must be after start_date",
                status_code=400,
            )

    if frequency not in ("daily", "weekly", "monthly"):
        raise AppError("VALIDATION_ERROR", "Invalid frequency", status_code=400)
    if frequency == "weekly" and day_of_week is None:
        raise AppError(
            "VALIDATION_ERROR",
            "day_of_week is required for weekly frequency",
            status_code=400,
        )
    if frequency == "monthly" and day_of_month is None:
        raise AppError(
            "VALIDATION_ERROR",
            "day_of_month is required for monthly frequency",
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

    next_d = scheduler_service.compute_initial_next_execution(
        start_date,
        frequency,
        day_of_month,
        day_of_week,
    )

    rid = str(uuid.uuid4())
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    await conn.execute(
        """
        INSERT INTO recurring_payments (
            id, sender_wallet_id, receiver_wallet_id, amount, currency, description,
            frequency, day_of_month, day_of_week, next_execution_date, status,
            start_date, end_date, total_executions, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 0, ?, ?)
        """,
        (
            rid,
            sender_wallet_id,
            receiver_wallet_id,
            amount_paise,
            sender["currency"],
            description,
            frequency,
            day_of_month,
            day_of_week,
            next_d.isoformat(),
            start_date.isoformat(),
            end_date.isoformat() if end_date else None,
            ts,
            ts,
        ),
    )
    return await get_recurring_by_id(conn, rid)


async def get_recurring_by_id(conn: aiosqlite.Connection, rid: str) -> dict:
    row = await fetch_one(
        conn,
        "SELECT * FROM recurring_payments WHERE id = ?",
        (rid,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Recurring payment not found", status_code=404)
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
        "frequency": row["frequency"],
        "day_of_month": row["day_of_month"],
        "day_of_week": row["day_of_week"],
        "next_execution_date": row["next_execution_date"],
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "total_executions": row["total_executions"],
        "last_executed_at": row["last_executed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_recurring(
    conn: aiosqlite.Connection,
    *,
    actor_user_id: str,
    actor_role: str,
    wallet_id: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict], object]:
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
            if own is None or own["user_id"] != actor_user_id:
                raise AppError("FORBIDDEN", "Cannot list for this wallet", status_code=403)
    elif actor_role != "admin":
        conds.append(
            "sender_wallet_id IN (SELECT id FROM wallets WHERE user_id = ?)"
        )
        params.append(actor_user_id)

    where = " AND ".join(conds) if conds else "1=1"

    count_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM recurring_payments WHERE {where}",
        tuple(params),
    )
    assert count_row is not None
    total = int(count_row["c"])

    off = offset_for_page(page, limit)
    params2 = list(params) + [limit, off]
    rows = await fetch_all(
        conn,
        f"""
        SELECT * FROM recurring_payments WHERE {where}
        ORDER BY next_execution_date ASC, created_at ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params2),
    )
    meta = build_meta(page=page, limit=limit, total=total)
    return [_row_to_dict(r) for r in rows], meta
