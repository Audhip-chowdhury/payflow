"""Fraud rules and flagged queue (Phase 5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FraudRuleCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    rule_type: Literal["velocity", "amount_threshold", "geo_anomaly", "pattern"]
    config: dict[str, Any]
    action: Literal["flag", "block", "alert"] = "flag"


class FlaggedRelease(BaseModel):
    notes: str = Field(..., min_length=1)
