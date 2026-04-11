"""Atomic transfers + idempotency + fraud rules (Phase 5)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite

from payflow.database import fetch_one
from payflow.exceptions import AppError
from payflow.services import fraud_service, idempotency_service, rate_limit_service
from payflow.utils.currency import paise_to_sim, sim_to_paise


def _parse_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as e:
        raise AppError(
            "VALIDATION_ERROR",
            f"Invalid UUID for {field}",
            status_code=400,
            details={"field": field},
        ) from e


async def transfer_funds_atomic(
    conn: aiosqlite.Connection,
    *,
    sender_wallet_id: str,
    receiver_wallet_id: str,
    amount_paise: int,
    description: str | None,
    reference_type: str,
    reference_id: str | None,
) -> dict[str, Any]:
    """
    Move funds between wallets; runs fraud rules (Phase 5).
    Returns API-style `data` dict for one transfer (status completed or held).
    """
    if amount_paise <= 0:
        raise AppError(
            "VALIDATION_ERROR",
            "Amount must be greater than zero",
            status_code=400,
        )

    sender_wallet_id = _parse_uuid(sender_wallet_id, "sender_wallet_id")
    receiver_wallet_id = _parse_uuid(receiver_wallet_id, "receiver_wallet_id")

    if sender_wallet_id == receiver_wallet_id:
        raise AppError(
            "VALIDATION_ERROR",
            "Cannot transfer to the same wallet",
            status_code=400,
        )

    rate_limit_service.check_transfer_rate_limit(sender_wallet_id)

    sender = await fetch_one(
        conn,
        "SELECT * FROM wallets WHERE id = ?",
        (sender_wallet_id,),
    )
    if sender is None:
        raise AppError("NOT_FOUND", "Sender wallet not found", status_code=404)
    if sender["status"] != "active":
        raise AppError(
            "INVALID_STATE",
            "Sender wallet is not active",
            status_code=422,
        )

    receiver = await fetch_one(
        conn,
        "SELECT * FROM wallets WHERE id = ?",
        (receiver_wallet_id,),
    )
    if receiver is None:
        raise AppError("NOT_FOUND", "Receiver wallet not found", status_code=404)
    if receiver["status"] != "active":
        raise AppError(
            "INVALID_STATE",
            "Receiver wallet is not active",
            status_code=422,
        )
    if sender["currency"] != receiver["currency"]:
        raise AppError(
            "VALIDATION_ERROR",
            "Sender and receiver wallets must use the same currency",
            status_code=400,
        )

    bal = int(sender["balance"])
    if bal < amount_paise:
        raise AppError(
            "INSUFFICIENT_BALANCE",
            "Wallet has insufficient funds for this transfer",
            status_code=422,
        )

    sender_user_id = str(sender["user_id"])

    outcome, rule_id, reason = await fraud_service.evaluate_rules_for_transfer(
        conn,
        sender_wallet_id=sender_wallet_id,
        _sender_user_id=sender_user_id,
        amount_paise=amount_paise,
    )

    tx_id = str(uuid.uuid4())
    now_row = await fetch_one(conn, "SELECT datetime('now') as t")
    assert now_row is not None
    ts = now_row["t"]

    await conn.execute(
        """
        INSERT INTO transactions (
            id, type, status, sender_wallet_id, receiver_wallet_id,
            amount, currency, reference_id, reference_type, description, metadata, created_at
        ) VALUES (?, 'transfer', 'pending', ?, ?, ?, ?, ?, ?, ?, '{}', ?)
        """,
        (
            tx_id,
            sender_wallet_id,
            receiver_wallet_id,
            amount_paise,
            sender["currency"],
            reference_id,
            reference_type,
            description,
            ts,
        ),
    )

    if outcome == "block":
        await conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        raise AppError(
            "FRAUD_BLOCKED",
            reason or "Transfer blocked by fraud policy",
            status_code=403,
            details={"rule_id": rule_id} if rule_id else {},
        )

    new_sender = bal - amount_paise
    new_receiver = int(receiver["balance"]) + amount_paise
    final_status = "held" if outcome == "flag" else "completed"

    await conn.execute(
        """
        UPDATE wallets SET balance = ?, updated_at = ? WHERE id = ?
        """,
        (new_sender, ts, sender_wallet_id),
    )
    await conn.execute(
        """
        UPDATE wallets SET balance = ?, updated_at = ? WHERE id = ?
        """,
        (new_receiver, ts, receiver_wallet_id),
    )

    await conn.execute(
        """
        UPDATE transactions SET status = ? WHERE id = ?
        """,
        (final_status, tx_id),
    )

    if outcome == "flag" and rule_id:
        await fraud_service.insert_flagged(
            conn,
            transaction_id=tx_id,
            rule_id=rule_id,
            reason=reason or "Fraud rule matched",
        )

    rate_limit_service.record_transfer_event(sender_wallet_id)

    return {
        "transaction_id": tx_id,
        "sender_wallet_id": sender_wallet_id,
        "receiver_wallet_id": receiver_wallet_id,
        "amount": paise_to_sim(amount_paise),
        "status": final_status,
        "created_at": ts,
    }


async def execute_transfer(
    conn: aiosqlite.Connection,
    *,
    user_id: str,
    sender_wallet_id: str,
    receiver_wallet_id: str,
    amount_str: str,
    description: str | None,
    idempotency_key: str | None,
    endpoint: str,
    payload_dict: dict[str, Any],
    skip_idempotency_read: bool = False,
) -> tuple[dict[str, Any], int]:
    try:
        amount_paise = sim_to_paise(amount_str)
    except ValueError as e:
        raise AppError(
            "VALIDATION_ERROR",
            "Invalid amount format or value",
            status_code=400,
        ) from e
    if amount_paise <= 0:
        raise AppError(
            "VALIDATION_ERROR",
            "Amount must be greater than zero",
            status_code=400,
        )

    sender_wallet_id = _parse_uuid(sender_wallet_id, "sender_wallet_id")
    receiver_wallet_id = _parse_uuid(receiver_wallet_id, "receiver_wallet_id")

    if idempotency_key and not skip_idempotency_read:
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

    sender = await fetch_one(
        conn,
        "SELECT * FROM wallets WHERE id = ?",
        (sender_wallet_id,),
    )
    if sender is None:
        raise AppError("NOT_FOUND", "Sender wallet not found", status_code=404)
    if sender["user_id"] != user_id:
        raise AppError(
            "FORBIDDEN",
            "You do not own the sender wallet",
            status_code=403,
        )

    data = await transfer_funds_atomic(
        conn,
        sender_wallet_id=sender_wallet_id,
        receiver_wallet_id=receiver_wallet_id,
        amount_paise=amount_paise,
        description=description,
        reference_type="transfer",
        reference_id=None,
    )

    body: dict[str, Any] = {"success": True, "data": data}
    if data.get("status") == "held":
        body["meta"] = {"warning": "Transfer flagged for review"}

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
