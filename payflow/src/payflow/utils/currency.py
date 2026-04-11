"""Money in smallest unit (paise) ↔ API string (2 decimal places)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def paise_to_sim(paise: int) -> str:
    """Convert integer paise to SimCash string e.g. 15000 -> \"150.00\"."""
    d = (Decimal(paise) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(d, "f")


def sim_to_paise(amount: str) -> int:
    """Parse SimCash string to paise; raises ValueError on bad input."""
    try:
        d = Decimal(amount.strip())
    except (InvalidOperation, AttributeError) as e:
        raise ValueError("invalid amount") from e
    if d != d.quantize(Decimal("0.01")):
        raise ValueError("amount must have at most 2 decimal places")
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))
