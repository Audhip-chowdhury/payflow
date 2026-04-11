"""User API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str = Field(..., description="ISO 8601 UTC")
    updated_at: str = Field(..., description="ISO 8601 UTC")
