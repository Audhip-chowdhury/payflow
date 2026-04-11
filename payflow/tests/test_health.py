"""Health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(async_client: AsyncClient) -> None:
    r = await async_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
