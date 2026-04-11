"""Transaction list models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TransactionListItem(BaseModel):
    id: str
    type: str
    status: str
    sender_wallet_id: str | None
    receiver_wallet_id: str | None
    amount: str
    description: str | None
    created_at: str
