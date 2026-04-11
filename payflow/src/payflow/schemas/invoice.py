"""Invoice schemas (Phase 4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InvoiceCreate(BaseModel):
    vendor_id: str
    invoice_number: str = Field(..., max_length=50)
    amount: str
    currency: str = Field(default="SIM", max_length=10)
    description: str | None = None
    payer_wallet_id: str
