"""Fraud rules evaluation, flagged queue, release (Phase 5). PF-017 velocity uses wallet scope only."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

import aiosqlite

from payflow.database import fetch_all, fetch_one
from payflow.exceptions import AppError
from payflow.utils.pagination import build_meta

Outcome = Literal["complete", "flag", "block"]


async def create_rule(
    conn: aiosqlite.Connection,
    *,
    name: str,
    description: str | None,
    rule_type: str,
    config: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    rid = str(uuid.uuid4())
    now = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now is not None
    ts = now["t"]
    cfg = json.dumps(config)
    await conn.execute(
        """
        INSERT INTO fraud_rules (id, name, description, rule_type, config, is_active, action, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (rid, name, description, rule_type, cfg, action, ts, ts),
    )
    return await get_rule(conn, rid)


async def get_rule(conn: aiosqlite.Connection, rule_id: str) -> dict[str, Any]:
    row = await fetch_one(conn, "SELECT * FROM fraud_rules WHERE id = ?", (rule_id,))
    if row is None:
        raise AppError("NOT_FOUND", "Fraud rule not found", status_code=404)
    return _rule_row(row)


def _rule_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "rule_type": row["rule_type"],
        "config": json.loads(row["config"] or "{}"),
        "is_active": bool(row["is_active"]),
        "action": row["action"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_active_rules(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        "SELECT * FROM fraud_rules WHERE is_active = 1 ORDER BY created_at ASC",
    )
    return [_rule_row(r) for r in rows]


async def _count_velocity_pf017(
    conn: aiosqlite.Connection,
    *,
    sender_wallet_id: str,
    window_minutes: int,
) -> int:
    """PF-017: counts by sender_wallet_id only (ignores user-level aggregation)."""
    mod = f"-{window_minutes} minutes"
    row = await fetch_one(
        conn,
        """
        SELECT COUNT(*) AS c FROM transactions
        WHERE sender_wallet_id = ?
          AND status = 'completed'
          AND created_at > datetime('now', ?)
        """,
        (sender_wallet_id, mod),
    )
    return int(row["c"]) if row else 0


async def evaluate_rules_for_transfer(
    conn: aiosqlite.Connection,
    *,
    sender_wallet_id: str,
    _sender_user_id: str,
    amount_paise: int,
) -> tuple[Outcome, str | None, str | None]:
    """
    Returns (outcome, rule_id, reason).
    Block takes precedence over flag.
    """
    rules = await list_active_rules(conn)
    first_flag: tuple[str, str] | None = None

    for rule in rules:
        rt = rule["rule_type"]
        cfg = rule["config"]
        action = rule["action"]
        rid = rule["id"]
        matched = False
        reason = ""

        if rt == "velocity":
            window = int(cfg.get("window_minutes", 60))
            max_tx = int(cfg.get("max_transactions", 10))
            count = await _count_velocity_pf017(
                conn, sender_wallet_id=sender_wallet_id, window_minutes=window
            )
            if count >= max_tx:
                matched = True
                reason = (
                    f"Velocity: {count} completed transfers in {window} minutes "
                    f"(limit {max_tx}) for this sender wallet"
                )

        elif rt == "amount_threshold":
            max_amt = int(cfg.get("max_amount", 0))
            per_tx = bool(cfg.get("per_transaction", True))
            if per_tx and amount_paise > max_amt:
                matched = True
                reason = f"Amount {amount_paise} paise exceeds threshold {max_amt}"

        elif rt in ("geo_anomaly", "pattern"):
            matched = False

        if not matched:
            continue

        if action == "block":
            return ("block", rid, reason)
        if action in ("flag", "alert") and first_flag is None:
            first_flag = (rid, reason)

    if first_flag:
        return ("flag", first_flag[0], first_flag[1])
    return ("complete", None, None)


async def insert_flagged(
    conn: aiosqlite.Connection,
    *,
    transaction_id: str,
    rule_id: str,
    reason: str,
) -> str:
    fid = str(uuid.uuid4())
    now = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now is not None
    ts = now["t"]
    await conn.execute(
        """
        INSERT INTO flagged_transactions (id, transaction_id, rule_id, reason, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (fid, transaction_id, rule_id, reason, ts),
    )
    return fid


async def list_flagged(
    conn: aiosqlite.Connection,
    *,
    status: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], Any]:
    params: list[Any] = []
    wh = ""
    if status:
        wh = " WHERE f.status = ?"
        params.append(status)
    count_row = await fetch_one(
        conn,
        f"SELECT COUNT(*) AS c FROM flagged_transactions f{wh}",
        tuple(params),
    )
    total = int(count_row["c"]) if count_row else 0
    off = (page - 1) * limit
    rows = await fetch_all(
        conn,
        f"""
        SELECT f.*, t.amount, t.currency, t.sender_wallet_id, t.receiver_wallet_id, t.status AS tx_status,
               r.name AS rule_name
        FROM flagged_transactions f
        JOIN transactions t ON t.id = f.transaction_id
        JOIN fraud_rules r ON r.id = f.rule_id
        {wh}
        ORDER BY f.created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (limit, off),
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "transaction_id": r["transaction_id"],
                "rule_id": r["rule_id"],
                "rule_name": r["rule_name"],
                "reason": r["reason"],
                "status": r["status"],
                "amount": r["amount"],
                "currency": r["currency"],
                "sender_wallet_id": r["sender_wallet_id"],
                "receiver_wallet_id": r["receiver_wallet_id"],
                "transaction_status": r["tx_status"],
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_notes": r["review_notes"],
                "created_at": r["created_at"],
            }
        )
    return out, build_meta(page=page, limit=limit, total=total)


async def release_flagged(
    conn: aiosqlite.Connection,
    *,
    flagged_id: str,
    reviewer_id: str,
    notes: str,
    actor_role: str,
) -> dict[str, Any]:
    """Admin-only: pending → released, transaction held → completed. PF-019: no webhook here."""
    if actor_role != "admin":
        raise AppError("FORBIDDEN", "Only admins can release flagged transfers", status_code=403)

    row = await fetch_one(
        conn,
        """
        SELECT f.*, t.status AS tx_status
        FROM flagged_transactions f
        JOIN transactions t ON t.id = f.transaction_id
        WHERE f.id = ?
        """,
        (flagged_id,),
    )
    if row is None:
        raise AppError("NOT_FOUND", "Flagged record not found", status_code=404)
    if row["status"] != "pending":
        raise AppError(
            "INVALID_STATE",
            "Only pending flagged items can be released",
            status_code=422,
        )
    if row["tx_status"] != "held":
        raise AppError(
            "INVALID_STATE",
            "Transaction is not in held status",
            status_code=422,
        )

    now = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now is not None
    ts = now["t"]
    tx_id = row["transaction_id"]

    await conn.execute(
        """
        UPDATE flagged_transactions SET
          status = 'released',
          reviewed_by = ?,
          reviewed_at = ?,
          review_notes = ?
        WHERE id = ?
        """,
        (reviewer_id, ts, notes, flagged_id),
    )
    await conn.execute(
        """
        UPDATE transactions SET status = 'completed' WHERE id = ?
        """,
        (tx_id,),
    )

    return {
        "flagged_id": flagged_id,
        "transaction_id": tx_id,
        "status": "released",
    }
