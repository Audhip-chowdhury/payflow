"""Transaction history."""

from __future__ import annotations

from fastapi import APIRouter, Query

from payflow.database import get_connection
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.transaction import TransactionListItem
from payflow.services import transaction_service

router = APIRouter(prefix="/api/v1", tags=["transactions"])


@router.get("/transactions", response_model=SuccessResponse[list[TransactionListItem]])
async def list_transactions(
    user: UserDep,
    wallet_id: str = Query(..., description="Wallet to list activity for"),
    txn_type: str | None = Query(None, alias="type"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    sort: str = Query("created_at:desc"),
) -> SuccessResponse[list[TransactionListItem]]:
    async with get_connection() as conn:
        items, meta = await transaction_service.list_transactions(
            conn,
            wallet_id=wallet_id,
            actor_user_id=user["id"],
            actor_role=user["role"],
            type_filter=txn_type,
            page=page,
            limit=limit,
            sort=sort,
        )
    data = [TransactionListItem.model_validate(i) for i in items]
    return SuccessResponse(success=True, data=data, meta=meta)
