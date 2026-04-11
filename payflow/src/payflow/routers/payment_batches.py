"""Payment batch execution (Phase 4)."""

from __future__ import annotations

from fastapi import APIRouter

from payflow.database import transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.services import payment_batch_service

router = APIRouter(prefix="/api/v1", tags=["payment-batches"])


@router.post("/payment-batches/execute")
async def execute_payment_batch(
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await payment_batch_service.execute_batch(
            conn, actor_role=user["role"]
        )
    return SuccessResponse(success=True, data=data)
