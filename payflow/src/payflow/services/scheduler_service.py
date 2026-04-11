"""Next execution dates for recurring payments (calendar-safe)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def _spec_dow_to_python_weekday(spec_dow: int) -> int:
    """Spec: 0=Sunday … 6=Saturday. Python weekday(): Monday=0 … Sunday=6."""
    return (spec_dow + 6) % 7


def first_weekly_occurrence_on_or_after(start: date, spec_day_of_week: int) -> date:
    py_wd = _spec_dow_to_python_weekday(spec_day_of_week)
    d = start
    while d.weekday() != py_wd:
        d += timedelta(days=1)
    return d


def first_monthly_occurrence_on_or_after(start: date, day_of_month: int) -> date:
    y, m = start.year, start.month
    for _ in range(0, 24):
        last = calendar.monthrange(y, m)[1]
        dom = min(day_of_month, last)
        cand = date(y, m, dom)
        if cand >= start:
            return cand
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    raise RuntimeError("could not find monthly occurrence")


def compute_initial_next_execution(
    start: date,
    frequency: str,
    day_of_month: int | None,
    day_of_week: int | None,
) -> date:
    if frequency == "daily":
        return start
    if frequency == "weekly":
        if day_of_week is None:
            raise ValueError("day_of_week required for weekly")
        return first_weekly_occurrence_on_or_after(start, day_of_week)
    if frequency == "monthly":
        if day_of_month is None:
            raise ValueError("day_of_month required for monthly")
        return first_monthly_occurrence_on_or_after(start, day_of_month)
    raise ValueError(f"unknown frequency {frequency}")


def advance_next_execution(
    last_execution: date,
    frequency: str,
    day_of_month: int | None,
    day_of_week: int | None,
) -> date:
    if frequency == "daily":
        return last_execution + timedelta(days=1)
    if frequency == "weekly":
        if day_of_week is None:
            raise ValueError("day_of_week required for weekly")
        return last_execution + timedelta(days=7)
    if frequency == "monthly":
        if day_of_month is None:
            raise ValueError("day_of_month required for monthly")
        return _advance_one_month_clamped(last_execution, day_of_month)
    raise ValueError(f"unknown frequency {frequency}")


def _advance_one_month_clamped(from_date: date, day_of_month: int) -> date:
    """Next calendar month from from_date, clamp day to month length."""
    if from_date.month == 12:
        y, m = from_date.year + 1, 1
    else:
        y, m = from_date.year, from_date.month + 1
    last = calendar.monthrange(y, m)[1]
    dom = min(day_of_month, last)
    return date(y, m, dom)
