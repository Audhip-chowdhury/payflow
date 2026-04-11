"""Settlements report (Phase 4). PF-016 applies to CSV."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from payflow.database import get_connection
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.services import payment_batch_service

router = APIRouter(prefix="/api/v1", tags=["settlements"])


@router.get("/settlements")
async def list_settlements(
    user: UserDep,
    date_from: Annotated[str | None, Query()] = None,
    date_to: Annotated[str | None, Query()] = None,
    vendor_id: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    format: Annotated[str, Query(alias="format")] = "json",
):
    async with get_connection() as conn:
        payload, ctype = await payment_batch_service.list_settlements(
            conn,
            actor_role=user["role"],
            date_from=date_from,
            date_to=date_to,
            vendor_id=vendor_id,
            page=page,
            limit=limit,
            format_=format,
        )
    if ctype == "text/csv":
        return PlainTextResponse(content=payload, media_type="text/csv")
    assert isinstance(payload, dict)
    return SuccessResponse(success=True, data=payload["data"], meta=payload["meta"])
