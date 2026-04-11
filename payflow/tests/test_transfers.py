"""Transfer endpoint (Phase 1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import insert_user_and_wallet


@pytest.mark.asyncio
async def test_transfer_success(db_path, async_client: AsyncClient) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="u1",
        email="u1@t.com",
        api_key="k1",
        balance_paise=1_000_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="u2",
        email="u2@t.com",
        api_key="k2",
        balance_paise=0,
    )
    r = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "250.00",
            "description": "test",
        },
        headers={"X-API-Key": "k1", "Idempotency-Key": "t1"},
    )
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["amount"] == "250.00"
    assert d["status"] == "completed"


@pytest.mark.asyncio
async def test_transfer_insufficient(db_path, async_client: AsyncClient) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="p1",
        email="p1@t.com",
        api_key="kp1",
        balance_paise=100,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="p2",
        email="p2@t.com",
        api_key="kp2",
        balance_paise=0,
    )
    r = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "50.00",
        },
        headers={"X-API-Key": "kp1", "Idempotency-Key": "i1"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_transfer_self(db_path, async_client: AsyncClient) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="s1",
        email="s1@t.com",
        api_key="ks1",
        balance_paise=500,
    )
    r = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w1,
            "amount": "1.00",
        },
        headers={"X-API-Key": "ks1", "Idempotency-Key": "self1"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_transfer_zero_amount_rejected(db_path, async_client: AsyncClient) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="z1",
        email="z1@t.com",
        api_key="kz1",
        balance_paise=500,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="z2",
        email="z2@t.com",
        api_key="kz2",
        balance_paise=0,
    )
    r = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "0.00",
        },
        headers={"X-API-Key": "kz1", "Idempotency-Key": "z0"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_transfer_frozen_wallet(db_path, async_client: AsyncClient) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="f1",
        email="f1@t.com",
        api_key="kf1",
        balance_paise=500,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="f2",
        email="f2@t.com",
        api_key="kf2",
        balance_paise=0,
    )
    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(
            "UPDATE wallets SET status = 'frozen' WHERE id = ?",
            (w1,),
        )
        await conn.commit()
    finally:
        await conn.close()

    r = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "1.00",
        },
        headers={"X-API-Key": "kf1", "Idempotency-Key": "fr1"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_STATE"


@pytest.mark.asyncio
async def test_idempotency_same_key_same_payload(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="i1",
        email="i1@t.com",
        api_key="ki1",
        balance_paise=500_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="i2",
        email="i2@t.com",
        api_key="ki2",
        balance_paise=0,
    )
    payload = {
        "sender_wallet_id": w1,
        "receiver_wallet_id": w2,
        "amount": "10.00",
    }
    h = {"X-API-Key": "ki1", "Idempotency-Key": "same-key"}
    r1 = await async_client.post("/api/v1/transfers", json=payload, headers=h)
    r2 = await async_client.post("/api/v1/transfers", json=payload, headers=h)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_idempotency_conflict_different_payload(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="c1",
        email="c1@t.com",
        api_key="kc1",
        balance_paise=500_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="c2",
        email="c2@t.com",
        api_key="kc2",
        balance_paise=0,
    )
    h = {"X-API-Key": "kc1", "Idempotency-Key": "conflict-key"}
    await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "10.00",
        },
        headers=h,
    )
    r2 = await async_client.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "11.00",
        },
        headers=h,
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT"
