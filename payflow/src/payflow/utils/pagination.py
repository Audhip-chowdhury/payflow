"""Offset pagination helpers."""

from __future__ import annotations

from math import ceil

from payflow.schemas.common import PaginationMeta


def offset_for_page(page: int, limit: int) -> int:
    """0-based offset from 1-based page."""
    return (page - 1) * limit


def build_meta(*, page: int, limit: int, total: int) -> PaginationMeta:
    total_pages = ceil(total / limit) if limit > 0 else 0
    return PaginationMeta(
        page=page,
        limit=limit,
        total=total,
        total_pages=total_pages,
    )
