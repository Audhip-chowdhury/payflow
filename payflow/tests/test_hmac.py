"""HMAC helpers."""

from __future__ import annotations

from payflow.utils.hmac_utils import hmac_sha256_hex


def test_hmac_deterministic() -> None:
    a = hmac_sha256_hex("secret", "payload")
    b = hmac_sha256_hex("secret", "payload")
    assert a == b
    assert len(a) == 64


def test_hmac_secret_matters() -> None:
    a = hmac_sha256_hex("secret-a", "payload")
    b = hmac_sha256_hex("secret-b", "payload")
    assert a != b
