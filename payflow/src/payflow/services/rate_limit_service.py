"""Per-wallet transfer rate limits and per-user wallet-creation limits (Phase 5). PF-020."""

from __future__ import annotations

import time
from collections import defaultdict
from payflow.config import get_settings
from payflow.exceptions import AppError

# In-process sliding windows (single-worker assumption; tests run single process).
_transfer_events: dict[str, list[float]] = defaultdict(list)
_wallet_create_events: dict[str, list[float]] = defaultdict(list)


def _prune(events: list[float], window_seconds: float, now: float) -> None:
    cutoff = now - window_seconds
    while events and events[0] < cutoff:
        events.pop(0)


def check_transfer_rate_limit(sender_wallet_id: str) -> None:
    """Raises RATE_LIMIT_EXCEEDED if wallet would exceed transfers per window."""
    s = get_settings()
    max_n = s.rate_limit_transfers_per_wallet_per_minute
    window_sec = 60.0 * max(1, s.rate_limit_window_minutes)
    now = time.monotonic()
    ev = _transfer_events[sender_wallet_id]
    _prune(ev, window_sec, now)
    if len(ev) >= max_n:
        raise AppError(
            "RATE_LIMIT_EXCEEDED",
            "Too many transfers from this wallet; try again later",
            status_code=429,
        )


def record_transfer_event(sender_wallet_id: str) -> None:
    """Call after a transfer is accepted (completed, held, or pending cleared)."""
    now = time.monotonic()
    s = get_settings()
    window_sec = 60.0 * max(1, s.rate_limit_window_minutes)
    ev = _transfer_events[sender_wallet_id]
    _prune(ev, window_sec, now)
    ev.append(now)


def check_wallet_creation_rate_limit(user_id: str) -> None:
    """Raises RATE_LIMIT_EXCEEDED if user would exceed wallet creations per hour (PF-020)."""
    s = get_settings()
    max_n = s.rate_limit_wallet_creates_per_user_per_hour
    window_sec = 3600.0
    now = time.monotonic()
    ev = _wallet_create_events[user_id]
    _prune(ev, window_sec, now)
    if len(ev) >= max_n:
        raise AppError(
            "RATE_LIMIT_EXCEEDED",
            "Too many wallet creations; try again later",
            status_code=429,
        )


def record_wallet_created(user_id: str) -> None:
    now = time.monotonic()
    ev = _wallet_create_events[user_id]
    _prune(ev, 3600.0, now)
    ev.append(now)


def reset_limits_for_tests() -> None:
    """Test hook — clear in-memory counters."""
    _transfer_events.clear()
    _wallet_create_events.clear()
