"""Phase 3: expense reports, approvals, reimbursement, injected PF-009–012 behaviors."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade

COMPANY_USER_ID = "00000000-0000-4000-8000-0000000000b0"
COMPANY_WALLET_ID = "00000000-0000-4000-8000-0000000000c0"

CAT_TRAVEL = "00000000-0000-4000-8000-00000000ca01"
CAT_MEALS = "00000000-0000-4000-8000-00000000ca02"
CAT_SOFTWARE = "00000000-0000-4000-8000-00000000ca04"


async def _seed_expense_prereqs(db_path) -> None:
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        cur = await conn.execute("SELECT datetime('now')")
        now = (await cur.fetchone())[0]
        r = await conn.execute(
            "SELECT id FROM users WHERE id = ?", (COMPANY_USER_ID,)
        )
        if not await r.fetchone():
            await conn.execute(
                """
                INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
                VALUES (?, 'company', 'c@internal', 'pfk_co', 'admin', 1, ?, ?)
                """,
                (COMPANY_USER_ID, now, now),
            )
            await conn.execute(
                """
                INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
                VALUES (?, ?, 'SIM', ?, 'active', ?, ?)
                """,
                (COMPANY_WALLET_ID, COMPANY_USER_ID, 10_000_000_000, now, now),
            )
        for cid, name, plim in [
            (CAT_TRAVEL, "Travel", 1_000_000),
            (CAT_MEALS, "Meals & Entertainment", 500_000),
            (CAT_SOFTWARE, "Software & Tools", None),
        ]:
            ex = await conn.execute(
                "SELECT id FROM expense_categories WHERE id = ?", (cid,)
            )
            if await ex.fetchone():
                continue
            await conn.execute(
                """
                INSERT INTO expense_categories (id, name, policy_limit, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (cid, name, plim),
            )
        await conn.commit()
    finally:
        await conn.close()


async def _insert_user(
    db_path,
    *,
    username: str,
    api_key: str,
    role: str,
    balance_paise: int = 0,
) -> tuple[str, str]:
    uid = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        cur = await conn.execute("SELECT datetime('now')")
        now = (await cur.fetchone())[0]
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (uid, username, f"{username}@t.example", api_key, role, now, now),
        )
        await conn.execute(
            """
            INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
            VALUES (?, ?, 'SIM', ?, 'active', ?, ?)
            """,
            (wid, uid, balance_paise, now, now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return uid, wid


@pytest.fixture
async def expense_client(db_path, monkeypatch):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REIMBURSEMENT_WALLET_ID", COMPANY_WALLET_ID)
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    get_settings.cache_clear()
    run_alembic_upgrade()
    await _seed_expense_prereqs(db_path)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_report_policy_violation(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="u1", api_key="k1", role="employee", balance_paise=0)
    # Travel limit 10000 SIM = 1_000_000 paise — 10001.00 SIM exceeds
    body = {
        "title": "Too much",
        "line_items": [
            {
                "category_id": CAT_TRAVEL,
                "description": "x",
                "amount": "10001.00",
                "date": "2026-01-10",
            }
        ],
    }
    r = await expense_client.post(
        "/api/v1/expense-reports",
        json=body,
        headers={"X-API-Key": "k1"},
    )
    assert r.status_code == 400
    assert r.json()["success"] is False


@pytest.mark.asyncio
async def test_receipt_required_over_500_sim(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="u2", api_key="k2", role="employee")
    body = {
        "title": "Meal",
        "line_items": [
            {
                "category_id": CAT_MEALS,
                "description": "big dinner",
                "amount": "501.00",
                "date": "2026-01-10",
            }
        ],
    }
    r = await expense_client.post(
        "/api/v1/expense-reports",
        json=body,
        headers={"X-API-Key": "k2"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pf012_non_url_receipt_accepted(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="u3", api_key="k3", role="employee")
    body = {
        "title": "Bad URL ok",
        "line_items": [
            {
                "category_id": CAT_MEALS,
                "description": "meal",
                "amount": "501.00",
                "receipt_url": "javascript:alert(1)",
                "date": "2026-01-10",
            }
        ],
    }
    r = await expense_client.post(
        "/api/v1/expense-reports",
        json=body,
        headers={"X-API-Key": "k3"},
    )
    assert r.status_code == 201
    assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_submit_reimburse_happy_path(expense_client: AsyncClient, db_path) -> None:
    _, wid = await _insert_user(
        db_path, username="emp", api_key="ke", role="employee", balance_paise=0
    )
    await _insert_user(
        db_path, username="mgr", api_key="km", role="manager", balance_paise=0
    )
    d = (date.today() + timedelta(days=1)).isoformat()
    cr = await expense_client.post(
        "/api/v1/expense-reports",
        json={
            "title": "Trip",
            "line_items": [
                {
                    "category_id": CAT_SOFTWARE,
                    "description": "license",
                    "amount": "100.00",
                    "date": d,
                }
            ],
        },
        headers={"X-API-Key": "ke"},
    )
    assert cr.status_code == 201
    rid = cr.json()["data"]["id"]
    sr = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/submit",
        headers={"X-API-Key": "ke"},
    )
    assert sr.status_code == 200
    assert sr.json()["data"]["status"] == "submitted"
    ar = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/approve",
        json={"notes": "ok"},
        headers={"X-API-Key": "km"},
    )
    assert ar.status_code == 200
    assert ar.json()["data"]["status"] == "reimbursed"
    assert ar.json()["data"]["reimbursement"]["amount"] == "100.00"
    # Submitter wallet credited
    conn = await aiosqlite.connect(db_path)
    try:
        w = await (await conn.execute(
            "SELECT balance FROM wallets WHERE id = ?", (wid,)
        )).fetchone()
        assert int(w[0]) == 10_000
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pf011_exact_threshold_no_multi_level(expense_client: AsyncClient, db_path) -> None:
    """PF-011: strict `>` — total exactly 50000.00 SIM does not set multi-level."""
    await _insert_user(db_path, username="e2", api_key="ke2", role="employee")
    d = (date.today() + timedelta(days=1)).isoformat()
    cr = await expense_client.post(
        "/api/v1/expense-reports",
        json={
            "title": "Edge",
            "line_items": [
                {
                    "category_id": CAT_SOFTWARE,
                    "description": "x",
                    "amount": "50000.00",
                    "receipt_url": "https://x.example/r.pdf",
                    "date": d,
                }
            ],
        },
        headers={"X-API-Key": "ke2"},
    )
    assert cr.status_code == 201
    rid = cr.json()["data"]["id"]
    sr = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/submit",
        headers={"X-API-Key": "ke2"},
    )
    assert sr.status_code == 200
    assert sr.json()["data"]["requires_multi_level"] is False


@pytest.mark.asyncio
async def test_multi_level_two_approvals(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="e3", api_key="ke3", role="employee")
    await _insert_user(db_path, username="m1", api_key="km1", role="manager")
    await _insert_user(db_path, username="m2", api_key="km2", role="manager")
    d = (date.today() + timedelta(days=1)).isoformat()
    cr = await expense_client.post(
        "/api/v1/expense-reports",
        json={
            "title": "Big",
            "line_items": [
                {
                    "category_id": CAT_SOFTWARE,
                    "description": "x",
                    "amount": "60000.00",
                    "receipt_url": "https://x.example/r.pdf",
                    "date": d,
                }
            ],
        },
        headers={"X-API-Key": "ke3"},
    )
    rid = cr.json()["data"]["id"]
    await expense_client.post(
        f"/api/v1/expense-reports/{rid}/submit",
        headers={"X-API-Key": "ke3"},
    )
    a1 = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/approve",
        json={},
        headers={"X-API-Key": "km1"},
    )
    assert a1.status_code == 200
    assert a1.json()["data"]["status"] == "under_review"
    a2 = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/approve",
        json={},
        headers={"X-API-Key": "km2"},
    )
    assert a2.status_code == 200
    assert a2.json()["data"]["status"] == "reimbursed"


@pytest.mark.asyncio
async def test_pf009_manager_submitter_self_approve(expense_client: AsyncClient, db_path) -> None:
    """PF-009: no block when approver is submitter (manager)."""
    await _insert_user(
        db_path, username="lead", api_key="kl", role="manager", balance_paise=0
    )
    d = (date.today() + timedelta(days=1)).isoformat()
    cr = await expense_client.post(
        "/api/v1/expense-reports",
        json={
            "title": "Own",
            "line_items": [
                {
                    "category_id": CAT_SOFTWARE,
                    "description": "x",
                    "amount": "50.00",
                    "date": d,
                }
            ],
        },
        headers={"X-API-Key": "kl"},
    )
    rid = cr.json()["data"]["id"]
    await expense_client.post(
        f"/api/v1/expense-reports/{rid}/submit",
        headers={"X-API-Key": "kl"},
    )
    ar = await expense_client.post(
        f"/api/v1/expense-reports/{rid}/approve",
        json={},
        headers={"X-API-Key": "kl"},
    )
    assert ar.status_code == 200
    assert ar.json()["data"]["status"] == "reimbursed"


@pytest.mark.asyncio
async def test_pf010_bulk_mixed_200(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="e4", api_key="ke4", role="employee")
    await _insert_user(db_path, username="m3", api_key="km3", role="manager")
    d = (date.today() + timedelta(days=1)).isoformat()
    r_ok = await expense_client.post(
        "/api/v1/expense-reports",
        json={
            "title": "A",
            "line_items": [
                {
                    "category_id": CAT_SOFTWARE,
                    "description": "a",
                    "amount": "10.00",
                    "date": d,
                }
            ],
        },
        headers={"X-API-Key": "ke4"},
    )
    rid = r_ok.json()["data"]["id"]
    await expense_client.post(
        f"/api/v1/expense-reports/{rid}/submit",
        headers={"X-API-Key": "ke4"},
    )
    fake = str(uuid.uuid4())
    br = await expense_client.post(
        "/api/v1/expense-reports/bulk-action",
        json={"action": "approve", "report_ids": [rid, fake]},
        headers={"X-API-Key": "km3"},
    )
    assert br.status_code == 200
    results = br.json()["data"]["results"]
    assert any(x["status"] == "success" for x in results)
    assert any(x["status"] == "failed" for x in results)


@pytest.mark.asyncio
async def test_list_categories(expense_client: AsyncClient, db_path) -> None:
    await _insert_user(db_path, username="x", api_key="kx", role="employee")
    r = await expense_client.get(
        "/api/v1/expense-categories",
        headers={"X-API-Key": "kx"},
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 3
