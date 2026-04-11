"""Phase 5 — fraud rules, audit log, rate limits, PF-017–PF-020."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade
from payflow.services.rate_limit_service import reset_limits_for_tests
from tests.conftest import insert_user_and_wallet


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    reset_limits_for_tests()
    yield
    reset_limits_for_tests()


async def _admin_client(db_path, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    get_settings.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    key = "pfk_admin_phase5"
    uid = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active)
            VALUES (?, 'admin5', 'a5@test', ?, 'admin', 1)
            """,
            (uid, key),
        )
        await conn.commit()
    finally:
        await conn.close()
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": key})


@pytest.mark.asyncio
async def test_pf017_velocity_bypass_multiple_wallets(
    db_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PF-017: velocity counts per sender_wallet_id — same user can bypass via another wallet."""
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    get_settings.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    admin_key = "pfk_ad_pf017"
    uid_ad = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active)
            VALUES (?, 'adm', 'adm@t', ?, 'admin', 1)
            """,
            (uid_ad, admin_key),
        )
        await conn.commit()
    finally:
        await conn.close()

    u1, w_sim = await insert_user_and_wallet(
        db_path, username="u1", email="u1@t.com", api_key="k1", balance_paise=5_000_000
    )
    conn_e = await aiosqlite.connect(db_path)
    w_eur = str(uuid.uuid4())
    try:
        await conn_e.execute("PRAGMA foreign_keys=ON")
        nr = await conn_e.execute("SELECT datetime('now')")
        now = (await nr.fetchone())[0]
        await conn_e.execute(
            """
            INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
            VALUES (?, ?, 'EUR', ?, 'active', ?, ?)
            """,
            (w_eur, u1, 5_000_000, now, now),
        )
        await conn_e.commit()
    finally:
        await conn_e.close()

    uid_recv, w_recv_sim = await insert_user_and_wallet(
        db_path, username="recv", email="r@t.com", api_key="kr", balance_paise=0
    )
    conn_r = await aiosqlite.connect(db_path)
    w_recv_eur = str(uuid.uuid4())
    try:
        await conn_r.execute("PRAGMA foreign_keys=ON")
        nr = await conn_r.execute("SELECT datetime('now')")
        now = (await nr.fetchone())[0]
        await conn_r.execute(
            """
            INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
            VALUES (?, ?, 'EUR', ?, 'active', ?, ?)
            """,
            (w_recv_eur, uid_recv, 0, now, now),
        )
        await conn_r.commit()
    finally:
        await conn_r.close()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post(
            "/api/v1/fraud/rules",
            json={
                "name": "v3",
                "rule_type": "velocity",
                "config": {"max_transactions": 3, "window_minutes": 60, "scope": "sender"},
                "action": "block",
            },
            headers={"X-API-Key": admin_key},
        )
        h = {"X-API-Key": "k1"}
        for i in range(3):
            r = await ac.post(
                "/api/v1/transfers",
                json={
                    "sender_wallet_id": w_sim,
                    "receiver_wallet_id": w_recv_sim,
                    "amount": "1.00",
                    "description": str(i),
                },
                headers=h,
            )
            assert r.status_code == 201, r.text
        r4 = await ac.post(
            "/api/v1/transfers",
            json={
                "sender_wallet_id": w_sim,
                "receiver_wallet_id": w_recv_sim,
                "amount": "1.00",
            },
            headers=h,
        )
        assert r4.status_code == 403
        assert r4.json()["error"]["code"] == "FRAUD_BLOCKED"

        r_eur = await ac.post(
            "/api/v1/transfers",
            json={
                "sender_wallet_id": w_eur,
                "receiver_wallet_id": w_recv_eur,
                "amount": "1.00",
            },
            headers=h,
        )
        assert r_eur.status_code == 201


@pytest.mark.asyncio
async def test_pf018_audit_null_error_on_failed_transfer(
    db_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PF-018: audit row written before outcome; failed transfer still has error_message null."""
    ac = await _admin_client(db_path, monkeypatch)
    _, w1 = await insert_user_and_wallet(
        db_path, username="a18", email="a18@t.com", api_key="k18", balance_paise=100
    )
    _, w2 = await insert_user_and_wallet(
        db_path, username="b18", email="b18@t.com", api_key="k28", balance_paise=0
    )
    r = await ac.post(
        "/api/v1/transfers",
        json={
            "sender_wallet_id": w1,
            "receiver_wallet_id": w2,
            "amount": "500.00",
        },
        headers={"X-API-Key": "k18"},
    )
    assert r.status_code == 422
    ra = await ac.get("/api/v1/audit-log", params={"page": 1, "limit": 10})
    assert ra.status_code == 200
    rows = ra.json()["data"]
    assert any(
        e["entity_type"] == "wallet" and e["entity_id"] == w1 and e["error_message"] is None
        for e in rows
    )


@pytest.mark.asyncio
async def test_pf019_release_no_webhook(
    db_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PF-019: releasing a held transfer does not call webhook delivery."""
    ac = await _admin_client(db_path, monkeypatch)
    _, w1 = await insert_user_and_wallet(
        db_path, username="p19a", email="p19a@t.com", api_key="kp19a", balance_paise=5_000_000
    )
    _, w2 = await insert_user_and_wallet(
        db_path, username="p19b", email="p19b@t.com", api_key="kp19b", balance_paise=0
    )

    await ac.post(
        "/api/v1/fraud/rules",
        json={
            "name": "amt",
            "rule_type": "amount_threshold",
            "config": {"max_amount": 1, "per_transaction": True},
            "action": "flag",
        },
    )

    with patch(
        "payflow.services.webhook_service.notify_user_event",
        new_callable=AsyncMock,
    ) as mock_notify:
        r = await ac.post(
            "/api/v1/transfers",
            json={
                "sender_wallet_id": w1,
                "receiver_wallet_id": w2,
                "amount": "100.00",
            },
            headers={"X-API-Key": "kp19a"},
        )
        assert r.status_code == 201
        assert r.json()["data"]["status"] == "held"
        mock_notify.assert_not_called()

        listed = await ac.get("/api/v1/fraud/flagged", params={"status": "pending"})
        fid = listed.json()["data"][0]["id"]

        await ac.post(
            f"/api/v1/fraud/flagged/{fid}/release",
            json={"notes": "ok"},
        )
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_pf020_wallet_creation_rate_limit(
    db_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PF-020: separate cap on wallet creations per user per hour."""
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_WALLET_CREATES_PER_USER_PER_HOUR", "5")
    get_settings.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    key = "pfk_wlim"
    uid = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active)
            VALUES (?, 'wl', 'wl@t', ?, 'employee', 1)
            """,
            (uid, key),
        )
        await conn.commit()
    finally:
        await conn.close()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": key}
    ) as ac:
        for i in range(5):
            r = await ac.post(
                "/api/v1/wallets",
                json={"currency": f"C{i}"},
            )
            assert r.status_code == 201, r.text
        r6 = await ac.post("/api/v1/wallets", json={"currency": "C9"})
        assert r6.status_code == 429


@pytest.mark.asyncio
async def test_transfer_rate_limit_429(db_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_TRANSFERS_PER_WALLET_PER_MINUTE", "2")
    get_settings.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    _, w1 = await insert_user_and_wallet(
        db_path, username="rl", email="rl@t.com", api_key="krl", balance_paise=5_000_000
    )
    _, w2 = await insert_user_and_wallet(
        db_path, username="rl2", email="rl2@t.com", api_key="krl2", balance_paise=0
    )
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(2):
            r = await ac.post(
                "/api/v1/transfers",
                json={
                    "sender_wallet_id": w1,
                    "receiver_wallet_id": w2,
                    "amount": "1.00",
                },
                headers={"X-API-Key": "krl"},
            )
            assert r.status_code == 201
        r3 = await ac.post(
            "/api/v1/transfers",
            json={
                "sender_wallet_id": w1,
                "receiver_wallet_id": w2,
                "amount": "1.00",
            },
            headers={"X-API-Key": "krl"},
        )
        assert r3.status_code == 429
