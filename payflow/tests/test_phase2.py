"""Phase 2: scheduled payments, recurring, worker tick, webhooks."""

from __future__ import annotations

from datetime import date, timedelta

import aiosqlite
import pytest
from httpx import AsyncClient

from payflow.workers.payment_executor import run_due_payment_tick

from tests.conftest import insert_user_and_wallet


@pytest.mark.asyncio
async def test_create_scheduled_payment(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="s1",
        email="s1@t.com",
        api_key="ks1",
        balance_paise=500_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="s2",
        email="s2@t.com",
        api_key="ks2",
        balance_paise=0,
    )
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = await async_client.post(
        "/api/v1/scheduled-payments",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "100.00",
            "scheduled_date": tomorrow,
            "description": "later",
        },
        headers={"X-API-Key": "ks1"},
    )
    assert r.status_code == 201
    assert r.json()["data"]["status"] == "pending"


@pytest.mark.asyncio
async def test_list_scheduled_defaults_to_pending_only(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="lp1",
        email="lp1@t.com",
        api_key="klp1",
        balance_paise=100,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="lp2",
        email="lp2@t.com",
        api_key="klp2",
        balance_paise=0,
    )
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    await async_client.post(
        "/api/v1/scheduled-payments",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "1.00",
            "scheduled_date": tomorrow,
        },
        headers={"X-API-Key": "klp1"},
    )
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(
            "UPDATE scheduled_payments SET status = 'executed' WHERE sender_wallet_id = ?",
            (w1,),
        )
        await conn.commit()
    finally:
        await conn.close()

    r = await async_client.get(
        "/api/v1/scheduled-payments",
        headers={"X-API-Key": "klp1"},
    )
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_cancel_scheduled(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="c1",
        email="c1@t.com",
        api_key="kc1",
        balance_paise=100,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="c2",
        email="c2@t.com",
        api_key="kc2",
        balance_paise=0,
    )
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cr = await async_client.post(
        "/api/v1/scheduled-payments",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "1.00",
            "scheduled_date": tomorrow,
        },
        headers={"X-API-Key": "kc1"},
    )
    sid = cr.json()["data"]["id"]
    r = await async_client.patch(
        f"/api/v1/scheduled-payments/{sid}",
        json={"status": "cancelled"},
        headers={"X-API-Key": "kc1"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_worker_executes_due_scheduled(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="wex1",
        email="wex1@t.com",
        api_key="kwex1",
        balance_paise=1_000_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="wex2",
        email="wex2@t.com",
        api_key="kwex2",
        balance_paise=0,
    )
    today = date.today().isoformat()
    r = await async_client.post(
        "/api/v1/scheduled-payments",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "25.00",
            "scheduled_date": today,
        },
        headers={"X-API-Key": "kwex1"},
    )
    assert r.status_code == 201
    sid = r.json()["data"]["id"]

    await run_due_payment_tick()

    r2 = await async_client.get(
        f"/api/v1/scheduled-payments?status=executed",
        headers={"X-API-Key": "kwex1"},
    )
    assert r2.status_code == 200
    ids = [x["id"] for x in r2.json()["data"]]
    assert sid in ids


@pytest.mark.asyncio
async def test_create_recurring_daily(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="r1",
        email="r1@t.com",
        api_key="kr1",
        balance_paise=500_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="r2",
        email="r2@t.com",
        api_key="kr2",
        balance_paise=0,
    )
    start = date.today().isoformat()
    r = await async_client.post(
        "/api/v1/recurring-payments",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "5.00",
            "frequency": "daily",
            "start_date": start,
        },
        headers={"X-API-Key": "kr1"},
    )
    assert r.status_code == 201
    assert r.json()["data"]["frequency"] == "daily"


@pytest.mark.asyncio
async def test_create_webhook_subscription(
    db_path,
    async_client: AsyncClient,
) -> None:
    await insert_user_and_wallet(
        db_path,
        username="h1",
        email="h1@t.com",
        api_key="kh1",
        balance_paise=100,
    )
    r = await async_client.post(
        "/api/v1/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["payment.executed"],
            "secret": "whsec_test_secret_12345",
        },
        headers={"X-API-Key": "kh1"},
    )
    assert r.status_code == 201
    d = r.json()["data"]
    assert "id" in d
    assert d["events"] == ["payment.executed"]
