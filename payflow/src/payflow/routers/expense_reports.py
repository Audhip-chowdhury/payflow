"""Expense reports (Phase 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from payflow.database import get_connection, transaction_immediate
from payflow.deps import UserDep
from payflow.schemas.common import SuccessResponse
from payflow.schemas.expense_report import (
    ExpenseApprove,
    ExpenseBulkAction,
    ExpenseReject,
    ExpenseReportCreate,
)
from payflow.services import expense_report_service

router = APIRouter(prefix="/api/v1", tags=["expense-reports"])


@router.post("/expense-reports", status_code=201)
async def create_expense_report(
    body: ExpenseReportCreate,
    user: UserDep,
) -> SuccessResponse[dict]:
    payload = [li.model_dump() for li in body.line_items]
    async with transaction_immediate() as conn:
        data = await expense_report_service.create_report(
            conn,
            submitter_id=user["id"],
            title=body.title,
            line_items=payload,
        )
    return SuccessResponse(success=True, data=data)


@router.post("/expense-reports/{report_id}/submit")
async def submit_expense_report(
    report_id: str,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await expense_report_service.submit_report(
            conn, report_id=report_id, user_id=user["id"]
        )
    return SuccessResponse(success=True, data=data)


@router.post("/expense-reports/{report_id}/approve")
async def approve_expense_report(
    report_id: str,
    body: ExpenseApprove,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await expense_report_service.approve_report(
            conn,
            report_id=report_id,
            approver_id=user["id"],
            approver_role=user["role"],
            notes=body.notes,
        )
    return SuccessResponse(success=True, data=data)


@router.post("/expense-reports/{report_id}/reject")
async def reject_expense_report(
    report_id: str,
    body: ExpenseReject,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with transaction_immediate() as conn:
        data = await expense_report_service.reject_report(
            conn,
            report_id=report_id,
            actor_id=user["id"],
            actor_role=user["role"],
            reason=body.reason,
        )
    return SuccessResponse(success=True, data=data)


@router.post("/expense-reports/bulk-action")
async def bulk_expense_action(
    body: ExpenseBulkAction,
    user: UserDep,
) -> SuccessResponse[dict]:
    """PF-010: always HTTP 200 when the envelope is returned (handler does not raise)."""
    data = await expense_report_service.bulk_action(
        actor_id=user["id"],
        actor_role=user["role"],
        action=body.action,
        report_ids=body.report_ids,
        notes=body.notes,
        reason=body.reason,
    )
    return SuccessResponse(success=True, data=data)


@router.get("/expense-reports/{report_id}")
async def get_expense_report(
    report_id: str,
    user: UserDep,
) -> SuccessResponse[dict]:
    async with get_connection() as conn:
        data = await expense_report_service.get_report(
            conn,
            report_id=report_id,
            actor_id=user["id"],
            actor_role=user["role"],
        )
    return SuccessResponse(success=True, data=data)


@router.get("/expense-reports")
async def list_expense_reports(
    user: UserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    status: Annotated[str | None, Query()] = None,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows, meta = await expense_report_service.list_reports(
            conn,
            actor_id=user["id"],
            actor_role=user["role"],
            page=page,
            limit=limit,
            status=status,
        )
    return SuccessResponse(success=True, data=rows, meta=meta)


@router.get("/expense-categories")
async def list_expense_categories(
    user: UserDep,
) -> SuccessResponse[list[dict]]:
    async with get_connection() as conn:
        rows = await expense_report_service.list_categories(conn)
    return SuccessResponse(success=True, data=rows)
