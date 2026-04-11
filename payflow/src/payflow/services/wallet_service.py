"""Wallets — create, get, list."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.services import idempotency_service, rate_limit_service
from payflow.utils.currency import paise_to_sim


async def _ensure_user_active(conn: aiosqlite.Connection, user_id: str) -> None:
    row = await fetch_one(
        conn,
        "SELECT is_active FROM users WHERE id = ?",
        (user_id,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "User not found", status_code=404)
    if not row["is_active"]:
        raise AppError(
            "INVALID_STATE",
            "Inactive users cannot create wallets",
            status_code=422,
        )


async def create_wallet(
    conn: aiosqlite.Connection,
    *,
    user_id: str,
    currency: str,
    idempotency_key: str | None,
    endpoint: str,
    payload_dict: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """
    Create wallet. Idempotency optional; when key present, runs in caller's transaction.
    Returns (response_body_dict, http_status).
    """
    await _ensure_user_active(conn, user_id)

    if idempotency_key:
        key_hash = idempotency_service.compute_key_hash(
            idempotency_key, endpoint, user_id
        )
        payload_hash = idempotency_service.compute_payload_hash(payload_dict)
        existing = await idempotency_service.get_idempotency_record(conn, key_hash)
        if existing:
            if existing["request_payload_hash"] != payload_hash:
                raise AppError(
                    "CONFLICT",
                    "Idempotency key reused with different payload",
                    status_code=409,
                )
            body = json.loads(existing["response_body"])
            return body, int(existing["response_status"])

    dup = await fetch_one(
        conn,
        "SELECT id FROM wallets WHERE user_id = ? AND currency = ?",
        (user_id, currency),
    )
    if dup:
        raise AppError(
            "CONFLICT",
            f"A wallet for currency {currency} already exists",
            status_code=409,
        )

    rate_limit_service.check_wallet_creation_rate_limit(user_id)

    wid = str(uuid.uuid4())
    now = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now is not None
    ts = now["t"]
    await conn.execute(
        """
        INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
        VALUES (?, ?, ?, 0, 'active', ?, ?)
        """,
        (wid, user_id, currency, ts, ts),
    )

    data = {
        "id": wid,
        "user_id": user_id,
        "currency": currency,
        "balance": paise_to_sim(0),
        "status": "active",
        "created_at": ts,
        "updated_at": ts,
    }
    body = {"success": True, "data": data}

    rate_limit_service.record_wallet_created(user_id)

    if idempotency_key:
        key_hash = idempotency_service.compute_key_hash(
            idempotency_key, endpoint, user_id
        )
        payload_hash = idempotency_service.compute_payload_hash(payload_dict)
        await idempotency_service.insert_idempotency_record(
            conn,
            key_hash=key_hash,
            endpoint=endpoint,
            user_id=user_id,
            payload_hash=payload_hash,
            response_status=201,
            response_body_json=json.dumps(body),
        )

    return body, 201


def _row_to_wallet_public(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "currency": row["currency"],
        "balance": paise_to_sim(int(row["balance"])),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def get_wallet(
    conn: aiosqlite.Connection,
    *,
    wallet_id: str,
    actor_user_id: str,
    actor_role: str,
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        "SELECT * FROM wallets WHERE id = ?",
        (wallet_id,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Wallet not found", status_code=404)
    if actor_role != "admin" and row["user_id"] != actor_user_id:
        raise AppError(
            "FORBIDDEN",
            "You can only access your own wallets",
            status_code=403,
        )
    return _row_to_wallet_public(row)


async def list_wallets_for_user(
    conn: aiosqlite.Connection,
    *,
    actor_user_id: str,
    actor_role: str,
) -> list[dict[str, Any]]:
    if actor_role == "admin":
        rows = await fetch_all(conn, "SELECT * FROM wallets ORDER BY created_at DESC")
    else:
        rows = await fetch_all(
            conn,
            "SELECT * FROM wallets WHERE user_id = ? ORDER BY created_at DESC",
            (actor_user_id,),
        )
    return [_row_to_wallet_public(r) for r in rows]
