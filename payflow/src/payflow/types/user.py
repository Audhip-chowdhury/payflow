"""User row shape (matches users table)."""

from __future__ import annotations

from typing import TypedDict


class UserPublic(TypedDict):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str
    updated_at: str
