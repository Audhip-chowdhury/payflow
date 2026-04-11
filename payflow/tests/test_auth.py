"""API key authentication."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_API_KEY


@pytest.mark.asyncio
async def test_me_missing_key(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/me")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_me_invalid_key(async_client: AsyncClient) -> None:
    r = await async_client.get("/api/v1/me", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_me_valid_key(async_client_with_user: AsyncClient) -> None:
    r = await async_client_with_user.get(
        "/api/v1/me",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["username"] == "alice"
    assert body["data"]["role"] == "admin"
    assert "api_key" not in body["data"]
