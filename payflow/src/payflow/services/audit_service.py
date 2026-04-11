"""Immutable audit log (Phase 5). PF-018: failed operations may log with error_message null."""

from __future__ import annotations

import json
from typing import Any

from payflow.database import fetch_all, fetch_one
from payflow.utils.pagination import build_meta, offset_for_page


async def log_transfer_attempt_before(
    conn: aiosqlite.Connection,
    *,
    actor_id: str,
    sender_wallet_id: str,
    ip_address: str | None = None,
) -> None:
    """PF-018: Inserts audit row before outcome is known; error_message stays null on failure."""
    now = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now is not None
    ts = now["t"]
    await conn.execute(
        """
        INSERT INTO audit_log (
            entity_type, entity_id, action, actor_id, changes, metadata, error_message, ip_address, created_at
        ) VALUES (?, ?, 'transfer', ?, NULL, '{}', NULL, ?, ?)
        """,
        ("wallet", sender_wallet_id, actor_id, ip_address, ts),
    )


async def list_audit_log(
    conn: aiosqlite.Connection,
    *,
    entity_type: str | None,
    entity_id: str | None,
    actor_id: str | None,
    action: str | None,
    date_from: str | None,
    date_to: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], Any]:
    """Paginated audit log (admin)."""
    where: list[str] = []
    params: list[Any] = []
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        where.append("entity_id = ?")
        params.append(entity_id)
    if actor_id:
        where.append("actor_id = ?")
        params.append(actor_id)
    if action:
        where.append("action = ?")
        params.append(action)
    if date_from:
        where.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("created_at <= ?")
        params.append(date_to)
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    count_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM audit_log{wh}",
        tuple(params),
    )
    total = int(count_row["c"]) if count_row else 0
    off = offset_for_page(page, limit)
    rows = await fetch_all(
        conn,
        f"""
        SELECT id, entity_type, entity_id, action, actor_id, changes, metadata, error_message, ip_address, created_at
        FROM audit_log{wh}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (limit, off),
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "action": r["action"],
                "actor_id": r["actor_id"],
                "changes": json.loads(r["changes"]) if r["changes"] else None,
                "metadata": json.loads(r["metadata"] or "{}"),
                "error_message": r["error_message"],
                "ip_address": r["ip_address"],
                "created_at": r["created_at"],
            }
        )
    return out, build_meta(page=page, limit=limit, total=total)
