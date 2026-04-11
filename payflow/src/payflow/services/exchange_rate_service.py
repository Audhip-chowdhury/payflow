"""Latest FX row for SIM/SIM and cross pairs (Phase 4)."""

from __future__ import annotations

import uuid
from typing import Any

import aiosqlite

from payflow.database import fetch_one


async def get_latest_rate(
    conn: aiosqlite.Connection,
    from_currency: str,
    to_currency: str,
) -> float:
    row = await fetch_one(
        conn,
        """
        SELECT rate FROM exchange_rates
        WHERE from_currency = ? AND to_currency = ?
        ORDER BY effective_at DESC
        LIMIT 1
        """,
        (from_currency, to_currency),
    )
    if row is None:
        return 1.0
    return float(row["rate"])


async def insert_rate(
    conn: aiosqlite.Connection,
    *,
    from_currency: str,
    to_currency: str,
    rate: float,
) -> dict[str, Any]:
    rid = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO exchange_rates (id, from_currency, to_currency, rate, effective_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (rid, from_currency, to_currency, rate),
    )
    return {"id": rid, "from_currency": from_currency, "to_currency": to_currency, "rate": rate}
