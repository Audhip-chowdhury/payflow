"""Fraud rules and flagged transaction review (Phase 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from payflow.database import get_connection, transaction_immediate
from payflow.deps import AdminDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.fraud import FraudRuleCreate, FlaggedRelease
from payflow.services import fraud_service

router = APIRouter(prefix="/api/v1", tags=["fraud"])


@router.post("/fraud/rules", status_code=201)
async def create_fraud_rule(
    body: FraudRuleCreate,
    user: AdminDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await fraud_service.create_rule(
            conn,
            name=body.name,
            description=body.description,
            rule_type=body.rule_type,
            config=body.config,
            action=body.action,
        )
    return SuccessResponse(success=True, data=data)


@router.get("/fraud/flagged")
async def list_flagged(
    user: AdminDep,
    status: Annotated[str | None, Query(description="pending, released, blocked, escalated")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await fraud_service.list_flagged(
            conn, status=status, page=page, limit=limit
        )
    return SuccessResponse(success=True, data=rows, meta=meta)


@router.post("/fraud/flagged/{flagged_id}/release")
async def release_flagged(
    flagged_id: str,
    body: FlaggedRelease,
    user: AdminDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await fraud_service.release_flagged(
            conn,
            flagged_id=flagged_id,
            reviewer_id=user["id"],
            notes=body.notes,
            actor_role=user["role"],
        )
    return SuccessResponse(success=True, data=data)
