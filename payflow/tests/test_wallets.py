"""Wallet endpoints (Phase 1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import insert_user_and_wallet, insert_user_only


@pytest.mark.asyncio
async def test_create_wallet_requires_auth(async_client: AsyncClient) -> None:
    r = await async_client.post("/api/v1/wallets", json={"currency": "SIM"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_wallet_success(
    db_path,
    async_client: AsyncClient,
) -> None:
    await insert_user_only(
        db_path,
        username="solo",
        email="solo@t.com",
        api_key="pfk_solo",
    )
    r = await async_client.post(
        "/api/v1/wallets",
        json={"currency": "SIM"},
        headers={"X-API-Key": "pfk_solo"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["data"]["balance"] == "0.00"
    assert body["data"]["currency"] == "SIM"
    assert "updated_at" in body["data"]


@pytest.mark.asyncio
async def test_create_wallet_duplicate_currency(
    async_client_with_wallet: tuple[AsyncClient, str, str],
) -> None:
    client, key, _wid = async_client_with_wallet
    r = await client.post(
        "/api/v1/wallets",
        json={"currency": "SIM"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_create_wallet_inactive_user(
    db_path,
    async_client: AsyncClient,
) -> None:
    await insert_user_only(
        db_path,
        username="inact",
        email="in@t.com",
        api_key="pfk_in",
        is_active=0,
    )
    r = await async_client.post(
        "/api/v1/wallets",
        json={"currency": "SIM"},
        headers={"X-API-Key": "pfk_in"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_wallet_forbidden_other_user(
    db_path,
    async_client: AsyncClient,
) -> None:
    await insert_user_and_wallet(
        db_path,
        username="a",
        email="a@t.com",
        api_key="pfk_a",
        balance_paise=100,
    )
    _, w_other = await insert_user_and_wallet(
        db_path,
        username="b",
        email="b@t.com",
        api_key="pfk_b",
        balance_paise=100,
    )

    r = await async_client.get(
        f"/api/v1/wallets/{w_other}",
        headers={"X-API-Key": "pfk_a"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_wallets_balance_is_string(
    async_client_with_wallet: tuple[AsyncClient, str, str],
) -> None:
    client, key, wid = async_client_with_wallet
    r = await client.get("/api/v1/wallets", headers={"X-API-Key": key})
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) >= 1
    w = next(x for x in rows if x["id"] == wid)
    assert w["balance"] == "10000.00"
    assert isinstance(w["balance"], str)
