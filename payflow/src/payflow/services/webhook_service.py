"""Webhook subscriptions and HTTP delivery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.utils.hmac_utils import hmac_sha256_hex


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def create_subscription(
    conn: aiosqlite.Connection,
    *,
    user_id: str,
    url: str,
    events: list[str],
    secret: str,
) -> dict:
    if not url.startswith(("http://", "https://")):
        raise AppError(
            "VALIDATION_ERROR",
            "url must start with http:// or https://",
            status_code=400,
        )
    if not events:
        raise AppError(
            "VALIDATION_ERROR",
            "events must be a non-empty list",
            status_code=400,
        )

    sid = str(uuid.uuid4())
    ev_json = json.dumps(events)
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]
    await conn.execute(
        """
        INSERT INTO webhook_subscriptions (id, user_id, url, events, secret, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (sid, user_id, url, ev_json, secret, ts),
    )
    return await get_subscription(conn, sid)


async def get_subscription(conn: aiosqlite.Connection, sid: str) -> dict:
    row = await fetch_one(
        conn,
        "SELECT * FROM webhook_subscriptions WHERE id = ?",
        (sid,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Webhook subscription not found", status_code=404)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "url": row["url"],
        "events": json.loads(row["events"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


async def notify_user_event(
    user_id: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Fire webhooks for all active subscriptions of user that listen to event_type."""
    from payflow.database import get_connection

    rows: list = []
    async with get_connection() as conn:
        rows = await fetch_all(
            conn,
            """
            SELECT * FROM webhook_subscriptions
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        )

    ts = _utc_timestamp()
    payload: dict[str, Any] = {
        "event": event_type,
        "timestamp": ts,
        "data": data,
    }
    body_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    for sub in rows:
        evs = json.loads(sub["events"])
        if event_type not in evs:
            continue
        await _deliver_and_record(sub, event_type, payload, body_str)


async def _deliver_and_record(
    sub: aiosqlite.Row,
    event_type: str,
    payload: dict[str, Any],
    body_str: str,
) -> None:
    """Same body string for signature on every attempt (retry-safe)."""
    sig = hmac_sha256_hex(sub["secret"], body_str)
    delivery_id = str(uuid.uuid4())
    from payflow.database import get_connection

    async with get_connection() as conn:
        now_row = await fetch_one(conn, "SELECT datetime('now') as t")
        assert now_row is not None
        ts = now_row["t"]
        await conn.execute(
            """
            INSERT INTO webhook_deliveries (
                id, subscription_id, event_type, payload, attempt, status, created_at
            ) VALUES (?, ?, ?, ?, 1, 'pending', ?)
            """,
            (delivery_id, sub["id"], event_type, body_str, ts),
        )
        await conn.commit()

    attempt = 0
    last_status: int | None = None
    last_body: str | None = None
    err: str | None = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        while attempt < 3:
            attempt += 1
            try:
                r = await client.post(
                    sub["url"],
                    content=body_str.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-PayFlow-Signature": sig,
                    },
                )
                last_status = r.status_code
                last_body = r.text[:4000]
                if 200 <= r.status_code < 300:
                    async with get_connection() as conn:
                        await conn.execute(
                            """
                            UPDATE webhook_deliveries SET
                              response_status = ?, response_body = ?, attempt = ?,
                              delivered_at = datetime('now'), status = 'delivered'
                            WHERE id = ?
                            """,
                            (last_status, last_body, attempt, delivery_id),
                        )
                        await conn.commit()
                    return
            except Exception as e:
                err = str(e)
                last_status = None
                last_body = err[:4000]

            import asyncio

            await asyncio.sleep(min(2**attempt, 30))

    async with get_connection() as conn:
        await conn.execute(
            """
            UPDATE webhook_deliveries SET
              response_status = ?, response_body = ?, attempt = ?, status = 'failed'
            WHERE id = ?
            """,
            (last_status, last_body or err, attempt, delivery_id),
        )
        await conn.commit()
