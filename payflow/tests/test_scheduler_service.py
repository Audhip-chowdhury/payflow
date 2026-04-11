"""Scheduler date logic (Phase 2)."""

from __future__ import annotations

from datetime import date

from payflow.services.scheduler_service import (
    advance_next_execution,
    compute_initial_next_execution,
    first_monthly_occurrence_on_or_after,
)


def test_monthly_jan31_to_feb_clamped() -> None:
    n = advance_next_execution(
        date(2025, 1, 31),
        "monthly",
        31,
        None,
    )
    assert n == date(2025, 2, 28)


def test_monthly_feb28_to_mar31() -> None:
    n = advance_next_execution(
        date(2025, 2, 28),
        "monthly",
        31,
        None,
    )
    assert n == date(2025, 3, 31)


def test_daily_advances_one_day() -> None:
    d = date(2025, 6, 1)
    assert advance_next_execution(d, "daily", None, None) == date(2025, 6, 2)


def test_weekly_advances_seven_days() -> None:
    d = date(2025, 6, 2)
    n = advance_next_execution(d, "weekly", None, 0)  # day_of_week unused for advance delta
    assert n == date(2025, 6, 9)


def test_first_monthly_march31_on_or_after_march1() -> None:
    """Day 31 in March when starting March 1."""
    n = first_monthly_occurrence_on_or_after(date(2025, 3, 1), 31)
    assert n == date(2025, 3, 31)


def test_compute_initial_daily() -> None:
    s = date(2025, 1, 1)
    assert compute_initial_next_execution(s, "daily", None, None) == s
