"""Vendors (Phase 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from payflow.database import get_connection, transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.vendor import VendorCreate
from payflow.services import vendor_service

router = APIRouter(prefix="/api/v1", tags=["vendors"])


@router.post("/vendors", status_code=201)
async def create_vendor(
    body: VendorCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    bd = body.bank_details.model_dump() if body.bank_details else None
    async with transaction_immediate() as conn:
        data = await vendor_service.create_vendor(
            conn,
            actor_role=user["role"],
            name=body.name,
            email=body.email,
            tax_id=body.tax_id,
            payment_terms=body.payment_terms,
            bank_details=bd,
        )
    return SuccessResponse(success=True, data=data)


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(
    vendor_id: str,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await vendor_service.soft_delete_vendor(
            conn, actor_role=user["role"], vendor_id=vendor_id
        )
    return SuccessResponse(success=True, data=data)


@router.get("/vendors")
async def list_vendors(
    user: UserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await vendor_service.list_vendors(
            conn, actor_role=user["role"], page=page, limit=limit
        )
    return SuccessResponse(success=True, data=rows, meta=meta)
