"""Scheduled payment schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScheduledCreate(BaseModel):
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: str
    scheduled_date: str = Field(..., description="YYYY-MM-DD")
    description: str | None = None


class ScheduledPatch(BaseModel):
    status: Literal["cancelled"]
