"""Shared API envelope types."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: PaginationMeta | None = None
