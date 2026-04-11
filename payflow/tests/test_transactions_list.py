"""Transaction list pagination (Phase 1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import insert_user_and_wallet


@pytest.mark.asyncio
async def test_transactions_pagination_respects_limit(
    db_path,
    async_client: AsyncClient,
) -> None:
    _, w1 = await insert_user_and_wallet(
        db_path,
        username="t1",
        email="t1@t.com",
        api_key="kt1",
        balance_paise=10_000_000,
    )
    _, w2 = await insert_user_and_wallet(
        db_path,
        username="t2",
        email="t2@t.com",
        api_key="kt2",
        balance_paise=0,
    )
    for i in range(12):
        await async_client.post(
            "/api/v1/transfers",
            json={
                "sender_wallet_id": w1,
                "receiver_wallet_id": w2,
                "amount": "1.00",
                "description": f"x{i}",
            },
            headers={"X-API-Key": "kt1", "Idempotency-Key": f"pag{i}"},
        )

    r = await async_client.get(
        f"/api/v1/transactions?wallet_id={w1}&page=1&limit=10",
        headers={"X-API-Key": "kt1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 10
    assert body["meta"]["total"] >= 12
    assert body["meta"]["limit"] == 10
