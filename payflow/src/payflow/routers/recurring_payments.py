"""Recurring payments."""

from __future__ import annotations

from fastapi import APIRouter, Query

from payflow.database import get_connection
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.recurring_payment import RecurringCreate
from payflow.services import recurring_payment_service

router = APIRouter(prefix="/api/v1", tags=["recurring-payments"])


@router.post("/recurring-payments", status_code=201)
async def create_recurring(
    body: RecurringCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with get_connection() as conn:
        data = await recurring_payment_service.create_recurring(
            conn,
            user_id=user["id"],
            sender_wallet_id=body.sender_wallet_id,
            receiver_wallet_id=body.receiver_wallet_id,
            amount_str=body.amount,
            frequency=body.frequency,
            day_of_month=body.day_of_month,
            day_of_week=body.day_of_week,
            start_date_str=body.start_date,
            end_date_str=body.end_date,
            description=body.description,
        )
        await conn.commit()
    return SuccessResponse(success=True, data=data)


@router.get("/recurring-payments", response_model=SuccessResponse[list[dict]])
async def list_recurring(
    user: UserDep,
    wallet_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await recurring_payment_service.list_recurring(
            conn,
            actor_user_id=user["id"],
            actor_role=user["role"],
            wallet_id=wallet_id,
            page=page,
            limit=limit,
        )
    return SuccessResponse(success=True, data=rows, meta=meta)
