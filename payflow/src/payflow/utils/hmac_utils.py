"""HMAC signing for webhooks (Phase 2+)."""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(secret: str | bytes, message: str | bytes) -> str:
    """Return lowercase hex digest of HMAC-SHA256(secret, message)."""
    key = secret.encode() if isinstance(secret, str) else secret
    msg = message.encode() if isinstance(message, str) else message
    return hmac.new(key, msg, hashlib.sha256).hexdigest()
