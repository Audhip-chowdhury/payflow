"""Async SQLite access — raw SQL only; pragmas on every connection."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

from payflow.config import get_settings


async def _apply_pragmas(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    """One connection per use; closes after the context."""
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(settings.database_path)
    conn.row_factory = aiosqlite.Row
    try:
        await _apply_pragmas(conn)
        yield conn
    finally:
        await conn.close()


async def fetch_one(
    conn: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] | list[Any] | None = None,
) -> aiosqlite.Row | None:
    params = params or ()
    async with conn.execute(sql, params) as cursor:
        return await cursor.fetchone()


async def fetch_all(
    conn: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] | list[Any] | None = None,
) -> list[aiosqlite.Row]:
    params = params or ()
    async with conn.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        return list(rows)


async def execute(
    conn: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] | list[Any] | None = None,
) -> aiosqlite.Cursor:
    params = params or ()
    return await conn.execute(sql, params)


@asynccontextmanager
async def transaction_immediate() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Serialize writes — BEGIN IMMEDIATE then commit/rollback."""
    async with get_connection() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            await conn.rollback()
            raise
        else:
            await conn.commit()
