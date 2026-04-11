"""Transfers."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from payflow.database import get_connection, transaction_immediate
from payflow.exceptions import AppError
from payflow.deps import UserDep
from payflow.schemas.transfer import TransferCreate
from payflow.services import audit_service, idempotency_service, transfer_service, webhook_service

router = APIRouter(prefix="/api/v1", tags=["transfers"])


@router.post("/transfers", response_model=None)
async def create_transfer(
    body: TransferCreate,
    user: UserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    payload_dict = body.model_dump()
    user_id = user["id"]
    endpoint = "POST /api/v1/transfers"

    async with get_connection() as conn:
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
                return JSONResponse(
                    status_code=int(existing["response_status"]), content=body
                )
        await audit_service.log_transfer_attempt_before(
            conn,
            actor_id=user_id,
            sender_wallet_id=body.sender_wallet_id,
        )
        await conn.commit()

    async with transaction_immediate() as conn:
        raw, status = await transfer_service.execute_transfer(
            conn,
            user_id=user_id,
            sender_wallet_id=body.sender_wallet_id,
            receiver_wallet_id=body.receiver_wallet_id,
            amount_str=body.amount,
            description=body.description,
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            payload_dict=payload_dict,
            skip_idempotency_read=bool(idempotency_key),
        )
    if (
        status == 201
        and isinstance(raw, dict)
        and raw.get("success")
        and raw.get("data", {}).get("status") == "completed"
    ):
        d = raw["data"]
        await webhook_service.notify_user_event(
            user["id"],
            "payment.executed",
            {
                "transaction_id": d["transaction_id"],
                "amount": d["amount"],
                "sender_wallet_id": d["sender_wallet_id"],
                "receiver_wallet_id": d["receiver_wallet_id"],
            },
        )
    return JSONResponse(status_code=status, content=raw)
