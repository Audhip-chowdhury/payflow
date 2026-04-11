"""Idempotency key hashing and replay (must run inside the same write transaction)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import aiosqlite

from payflow.database import fetch_one


def compute_key_hash(idempotency_key: str, endpoint: str, user_id: str) -> str:
    raw = f"{idempotency_key}:{endpoint}:{user_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def compute_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def get_idempotency_record(
    conn: aiosqlite.Connection,
    key_hash: str,
) -> aiosqlite.Row | None:
    return await fetch_one(
        conn,
        """
        SELECT request_payload_hash, response_status, response_body
        FROM idempotency_store
        WHERE key_hash = ? AND datetime(expires_at) > datetime('now')
        """,
        (key_hash,),
    )


async def insert_idempotency_record(
    conn: aiosqlite.Connection,
    *,
    key_hash: str,
    endpoint: str,
    user_id: str,
    payload_hash: str,
    response_status: int,
    response_body_json: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO idempotency_store (
            key_hash, endpoint, api_key_id, request_payload_hash,
            response_status, response_body
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (key_hash, endpoint, user_id, payload_hash, response_status, response_body_json),
    )
