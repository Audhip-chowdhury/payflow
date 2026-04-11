"""Recurring payment schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecurringCreate(BaseModel):
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: str
    frequency: str = Field(..., pattern="^(daily|weekly|monthly)$")
    day_of_month: int | None = Field(None, ge=1, le=31)
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str | None = Field(None, description="YYYY-MM-DD or omit")
    description: str | None = None
