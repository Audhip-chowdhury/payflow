"""Scheduled one-off payments."""

from __future__ import annotations

from fastapi import APIRouter, Query

from payflow.database import get_connection
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.scheduled_payment import ScheduledCreate, ScheduledPatch
from payflow.services import scheduled_payment_service

router = APIRouter(prefix="/api/v1", tags=["scheduled-payments"])


@router.post("/scheduled-payments", status_code=201)
async def create_scheduled(
    body: ScheduledCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with get_connection() as conn:
        data = await scheduled_payment_service.create_scheduled(
            conn,
            user_id=user["id"],
            sender_wallet_id=body.sender_wallet_id,
            receiver_wallet_id=body.receiver_wallet_id,
            amount_str=body.amount,
            scheduled_date_str=body.scheduled_date,
            description=body.description,
        )
        await conn.commit()
    return SuccessResponse(success=True, data=data)


@router.get("/scheduled-payments", response_model=SuccessResponse[list[dict]])
async def list_scheduled(
    user: UserDep,
    status: str | None = Query(None),
    wallet_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await scheduled_payment_service.list_scheduled(
            conn,
            actor_user_id=user["id"],
            actor_role=user["role"],
            status=status,
            wallet_id=wallet_id,
            page=page,
            limit=limit,
        )
    return SuccessResponse(success=True, data=rows, meta=meta)


@router.patch("/scheduled-payments/{schedule_id}")
async def cancel_scheduled(
    schedule_id: str,
    body: ScheduledPatch,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with get_connection() as conn:
        data = await scheduled_payment_service.cancel_scheduled(
            conn,
            schedule_id=schedule_id,
            actor_user_id=user["id"],
            actor_role=user["role"],
        )
        await conn.commit()
    return SuccessResponse(success=True, data=data)
