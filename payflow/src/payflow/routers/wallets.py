"""Wallet CRUD."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from payflow.database import get_connection, transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.wallet import WalletCreate, WalletResponse
from payflow.services import wallet_service

router = APIRouter(prefix="/api/v1", tags=["wallets"])


@router.post("/wallets", response_model=None)
async def create_wallet(
    body: WalletCreate,
    user: UserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    payload_dict = body.model_dump()
    async with transaction_immediate() as conn:
        raw, status = await wallet_service.create_wallet(
            conn,
            user_id=user["id"],
            currency=body.currency,
            idempotency_key=idempotency_key,
            endpoint="POST /api/v1/wallets",
            payload_dict=payload_dict,
        )
    return JSONResponse(status_code=status, content=raw)


@router.get("/wallets", response_model=SuccessResponse[list[WalletResponse]])
async def list_wallets(
    user: UserDep,
) -> SuccessResponse[list[WalletResponse]]:
    async with get_connection() as conn:
        rows = await wallet_service.list_wallets_for_user(
            conn,
            actor_user_id=user["id"],
            actor_role=user["role"],
        )
    data = [WalletResponse.model_validate(r) for r in rows]
    return SuccessResponse(success=True, data=data)


@router.get("/wallets/{wallet_id}", response_model=SuccessResponse[WalletResponse])
async def get_wallet(
    wallet_id: str,
    user: UserDep,
) -> SuccessResponse[WalletResponse]:
    async with get_connection() as conn:
        row = await wallet_service.get_wallet(
            conn,
            wallet_id=wallet_id,
            actor_user_id=user["id"],
            actor_role=user["role"],
        )
    return SuccessResponse(success=True, data=WalletResponse.model_validate(row))
