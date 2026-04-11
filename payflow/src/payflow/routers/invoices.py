"""Invoices (Phase 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from payflow.database import get_connection, transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.invoice import InvoiceCreate
from payflow.services import invoice_service

router = APIRouter(prefix="/api/v1", tags=["invoices"])


@router.post("/invoices", status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await invoice_service.create_invoice(
            conn,
            actor_user_id=user["id"],
            vendor_id=body.vendor_id,
            invoice_number=body.invoice_number,
            amount_str=body.amount,
            currency=body.currency,
            description=body.description,
            payer_wallet_id=body.payer_wallet_id,
        )
    return SuccessResponse(success=True, data=data)


@router.post("/invoices/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: str,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await invoice_service.approve_invoice(
            conn, actor_role=user["role"], invoice_id=invoice_id
        )
    return SuccessResponse(success=True, data=data)


@router.get("/invoices")
async def list_invoices(
    user: UserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    status: Annotated[str | None, Query()] = None,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await invoice_service.list_invoices(
            conn,
            actor_user_id=user["id"],
            actor_role=user["role"],
            page=page,
            limit=limit,
            status=status,
        )
    return SuccessResponse(success=True, data=rows, meta=meta)
