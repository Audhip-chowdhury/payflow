"""Wallet request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WalletCreate(BaseModel):
    currency: str = Field(default="SIM", max_length=10)


class WalletResponse(BaseModel):
    id: str
    user_id: str
    currency: str
    balance: str
    status: str
    created_at: str
    updated_at: str
