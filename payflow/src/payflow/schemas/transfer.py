"""Transfer request/response models."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from payflow.utils.currency import sim_to_paise


class TransferCreate(BaseModel):
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: str = Field(..., description='SimCash string e.g. "250.00"')
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d{2}$", v.strip()):
            raise ValueError("Amount must match pattern NNNNNN.MM (two decimal places)")
        try:
            paise = sim_to_paise(v.strip())
        except ValueError as e:
            raise ValueError("Invalid amount") from e
        if paise <= 0:
            raise ValueError("Amount must be greater than zero")
        return v.strip()


class TransferResponse(BaseModel):
    transaction_id: str
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: str
    status: str
    created_at: str
