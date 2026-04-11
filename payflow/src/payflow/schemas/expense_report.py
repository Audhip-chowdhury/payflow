"""Expense report request/response models (Phase 3). PF-012: receipt_url not validated as URL."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExpenseLineItemCreate(BaseModel):
    category_id: str
    description: str
    amount: str
    receipt_url: str | None = None
    date: str = Field(..., description="YYYY-MM-DD")


class ExpenseReportCreate(BaseModel):
    title: str = Field(..., max_length=200)
    line_items: list[ExpenseLineItemCreate] = Field(default_factory=list)


class ExpenseApprove(BaseModel):
    notes: str | None = None


class ExpenseReject(BaseModel):
    reason: str = Field(..., min_length=1)


class ExpenseBulkAction(BaseModel):
    action: Literal["approve", "reject"]
    report_ids: list[str] = Field(..., min_length=1)
    notes: str | None = None
    reason: str | None = None  # for reject
