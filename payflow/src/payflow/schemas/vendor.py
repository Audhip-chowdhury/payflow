"""Vendor schemas (Phase 4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BankDetails(BaseModel):
    bank_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None


class VendorCreate(BaseModel):
    name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=255)
    tax_id: str | None = Field(None, max_length=50)
    payment_terms: Literal["immediate", "net_15", "net_30", "net_60"] = "net_30"
    bank_details: BankDetails | None = None
