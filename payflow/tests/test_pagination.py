"""Pagination helpers."""

from __future__ import annotations

from payflow.utils.pagination import build_meta, offset_for_page


def test_offset_for_page() -> None:
    assert offset_for_page(1, 10) == 0
    assert offset_for_page(2, 10) == 10
    assert offset_for_page(3, 25) == 50


def test_build_meta() -> None:
    m = build_meta(page=1, limit=10, total=42)
    assert m.page == 1
    assert m.limit == 10
    assert m.total == 42
    assert m.total_pages == 5
