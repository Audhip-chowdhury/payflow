"""Webhook schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebhookCreate(BaseModel):
    url: str
    events: list[str] = Field(..., min_length=1)
    secret: str = Field(..., min_length=8)
