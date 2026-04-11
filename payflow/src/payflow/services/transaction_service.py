"""Transaction history listing."""

from __future__ import annotations

import re

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.schemas.common import PaginationMeta
from payflow.utils.currency import paise_to_sim
from payflow.utils.pagination import build_meta, offset_for_page


async def _assert_wallet_access(
    conn: aiosqlite.Connection,
    *,
    wallet_id: str,
    actor_user_id: str,
    actor_role: str,
) -> None:
    row = await fetch_one(
        conn,
        "SELECT user_id FROM wallets WHERE id = ?",
        (wallet_id,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Wallet not found", status_code=404)
    if actor_role != "admin" and row["user_id"] != actor_user_id:
        raise AppError(
            "FORBIDDEN",
            "You can only list transactions for your own wallets",
            status_code=403,
        )


def _parse_sort(sort: str) -> tuple[str, str]:
    m = re.match(r"^([a-zA-Z_]+):(asc|desc)$", sort.strip())
    if not m:
        return "created_at", "DESC"
    field, direction = m.group(1), m.group(2).upper()
    if field != "created_at":
        return "created_at", "DESC"
    return field, direction


async def list_transactions(
    conn: aiosqlite.Connection,
    *,
    wallet_id: str,
    actor_user_id: str,
    actor_role: str,
    type_filter: str | None,
    page: int,
    limit: int,
    sort: str,
) -> tuple[list[dict[str, str | None]], PaginationMeta]:
    await _assert_wallet_access(conn, wallet_id=wallet_id, actor_user_id=actor_user_id, actor_role=actor_role)

    field, direction = _parse_sort(sort)
    if field != "created_at":
        direction = "DESC"

    where = "(sender_wallet_id = ? OR receiver_wallet_id = ?)"
    params: list = [wallet_id, wallet_id]
    if type_filter:
        where += " AND type = ?"
        params.append(type_filter)

    count_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM transactions WHERE {where}",
        tuple(params),
    )
    assert count_row is not None
    total = int(count_row["c"])

    off = offset_for_page(page, limit)
    params_page = list(params) + [limit, off]

    rows = await fetch_all(
        conn,
        f"""
        SELECT id, type, status, sender_wallet_id, receiver_wallet_id,
               amount, description, created_at
        FROM transactions
        WHERE {where}
        ORDER BY created_at {direction}
        LIMIT ? OFFSET ?
        """,
        tuple(params_page),
    )

    items: list[dict[str, str | None]] = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "type": r["type"],
                "status": r["status"],
                "sender_wallet_id": r["sender_wallet_id"],
                "receiver_wallet_id": r["receiver_wallet_id"],
                "amount": paise_to_sim(int(r["amount"])),
                "description": r["description"],
                "created_at": r["created_at"],
            }
        )

    meta = build_meta(page=page, limit=limit, total=total)
    return items, meta
