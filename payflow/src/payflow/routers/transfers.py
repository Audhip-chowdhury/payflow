"""Transfers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from payflow.database import transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.transfer import TransferCreate
from payflow.services import transfer_service

router = APIRouter(prefix="/api/v1", tags=["transfers"])


@router.post("/transfers", response_model=None)
async def create_transfer(
    body: TransferCreate,
    user: UserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    payload_dict = body.model_dump()
    async with transaction_immediate() as conn:
        raw, status = await transfer_service.execute_transfer(
            conn,
            user_id=user["id"],
            sender_wallet_id=body.sender_wallet_id,
            receiver_wallet_id=body.receiver_wallet_id,
            amount_str=body.amount,
            description=body.description,
            idempotency_key=idempotency_key,
            endpoint="POST /api/v1/transfers",
            payload_dict=payload_dict,
        )
    return JSONResponse(status_code=status, content=raw)
