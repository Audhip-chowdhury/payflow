"""Immutable audit log query (Phase 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from payflow.database import get_connection
from payflow.deps import AdminDep
from payflow.schemas.common import SuccessResponse
from payflow.services import audit_service

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit-log")
async def get_audit_log(
    user: AdminDep,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    actor_id: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    date_from: Annotated[str | None, Query()] = None,
    date_to: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await audit_service.list_audit_log(
            conn,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
            page=page,
            limit=limit,
        )
    return SuccessResponse(success=True, data=rows, meta=meta)
