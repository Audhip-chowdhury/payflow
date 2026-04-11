"""Currency helpers."""

from __future__ import annotations

import pytest

from payflow.utils.currency import paise_to_sim, sim_to_paise


def test_paise_to_sim() -> None:
    assert paise_to_sim(15000) == "150.00"
    assert paise_to_sim(0) == "0.00"
    assert paise_to_sim(1) == "0.01"


def test_sim_to_paise() -> None:
    assert sim_to_paise("150.00") == 15000
    assert sim_to_paise("0.01") == 1


def test_sim_to_paise_invalid() -> None:
    with pytest.raises(ValueError):
        sim_to_paise("not-a-number")
    with pytest.raises(ValueError):
        sim_to_paise("1.001")
