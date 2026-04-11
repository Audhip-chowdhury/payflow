"""Vendor onboarding and soft-delete (Phase 4). PF-015: delete does not block pending invoices."""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.utils.pagination import build_meta, offset_for_page


async def create_vendor(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
    name: str,
    email: str,
    tax_id: str | None,
    payment_terms: str,
    bank_details: dict[str, Any] | None,
) -> dict[str, Any]:
    if actor_role != "admin":
        raise AppError("FORBIDDEN", "Only admins can create vendors", status_code=403)

    dup = await fetch_one(conn, "SELECT id FROM vendors WHERE email = ?", (email,))
    if dup:
        raise AppError("CONFLICT", "A vendor with this email already exists", status_code=409)

    vid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    api_key = "pfk_" + secrets.token_hex(24)
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    uname = f"vendor_{vid[:8]}"
    await conn.execute(
        """
        INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'vendor', 1, ?, ?)
        """,
        (uid, uname, email, api_key, ts, ts),
    )

    wid = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
        VALUES (?, ?, 'SIM', 0, 'active', ?, ?)
        """,
        (wid, uid, ts, ts),
    )

    bd_json = json.dumps(bank_details) if bank_details else None
    await conn.execute(
        """
        INSERT INTO vendors (
            id, name, email, tax_id, payment_terms, wallet_id, bank_details, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (vid, name, email, tax_id, payment_terms, wid, bd_json, ts, ts),
    )

    return await get_vendor_by_id(conn, vid)


async def get_vendor_by_id(conn: aiosqlite.Connection, vendor_id: str) -> dict[str, Any]:
    row = await fetch_one(conn, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
    if row is None:
        raise AppError("NOT_FOUND", "Vendor not found", status_code=404)
    return _row_to_dict(row)


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    bd = row["bank_details"]
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "tax_id": row["tax_id"],
        "payment_terms": row["payment_terms"],
        "wallet_id": row["wallet_id"],
        "bank_details": json.loads(bd) if bd else None,
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def soft_delete_vendor(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
    vendor_id: str,
) -> dict[str, Any]:
    """PF-015: does not check for pending invoices."""
    if actor_role != "admin":
        raise AppError("FORBIDDEN", "Only admins can delete vendors", status_code=403)

    row = await fetch_one(conn, "SELECT id FROM vendors WHERE id = ?", (vendor_id,))
    if row is None:
        raise AppError("NOT_FOUND", "Vendor not found", status_code=404)

    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]
    await conn.execute(
        """
        UPDATE vendors SET status = 'deleted', updated_at = ? WHERE id = ?
        """,
        (ts, vendor_id),
    )
    return {"id": vendor_id, "status": "deleted"}


async def list_vendors(
    conn: aiosqlite.Connection,
    *,
    actor_role: str,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], Any]:
    if actor_role != "admin":
        raise AppError("FORBIDDEN", "Only admins can list vendors", status_code=403)

    off = offset_for_page(page, limit)
    total_row = await fetch_one(conn, "SELECT COUNT(*) AS c FROM vendors")
    total = int(total_row["c"]) if total_row else 0

    rows = await fetch_all(
        conn,
        """
        SELECT * FROM vendors ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, off),
    )
    return [_row_to_dict(r) for r in rows], build_meta(page=page, limit=limit, total=total)
