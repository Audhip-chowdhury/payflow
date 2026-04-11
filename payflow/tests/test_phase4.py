"""Phase 4: vendors, invoices, batches, settlements; PF-013–016 behaviors."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade


@pytest.fixture
async def client_phase4(db_path, monkeypatch):
    monkeypatch.setenv("ENABLE_WORKER", "false")
    monkeypatch.setenv("ENABLE_BATCH_WORKER", "false")
    get_settings.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    get_settings.cache_clear()


async def _seed_admin_wallet(db_path) -> tuple[str, str]:
    import aiosqlite

    uid = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    key = "pfk_admin_p4"
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        cur = await conn.execute("SELECT datetime('now')")
        now = (await cur.fetchone())[0]
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
            VALUES (?, 'adm', 'a@t', ?, 'admin', 1, ?, ?)
            """,
            (uid, key, now, now),
        )
        await conn.execute(
            """
            INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
            VALUES (?, ?, 'SIM', ?, 'active', ?, ?)
            """,
            (wid, uid, 50_000_000, now, now),
        )
        await conn.execute(
            """
            INSERT INTO exchange_rates (id, from_currency, to_currency, rate, effective_at)
            VALUES (?, 'SIM', 'SIM', 1.0, ?)
            """,
            (str(uuid.uuid4()), now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return key, wid


@pytest.mark.asyncio
async def test_vendor_admin_only(client_phase4: AsyncClient, db_path) -> None:
    import aiosqlite

    uid = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        cur = await conn.execute("SELECT datetime('now')")
        now = (await cur.fetchone())[0]
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
            VALUES (?, 'emp', 'e@t', 'pfk_emp', 'employee', 1, ?, ?)
            """,
            (uid, now, now),
        )
        await conn.commit()
    finally:
        await conn.close()

    r = await client_phase4.post(
        "/api/v1/vendors",
        json={
            "name": "Acme",
            "email": "a@acme.io",
            "payment_terms": "net_30",
        },
        headers={"X-API-Key": "pfk_emp"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_vendor_create_and_invoice_batch_pf013(
    client_phase4: AsyncClient, db_path
) -> None:
    key, payer_wid = await _seed_admin_wallet(db_path)

    vr = await client_phase4.post(
        "/api/v1/vendors",
        json={
            "name": "VendorCo",
            "email": "v@vendor.io",
            "payment_terms": "immediate",
        },
        headers={"X-API-Key": key},
    )
    assert vr.status_code == 201
    vendor_id = vr.json()["data"]["id"]

    inv = await client_phase4.post(
        "/api/v1/invoices",
        json={
            "vendor_id": vendor_id,
            "invoice_number": "INV-P4-001",
            "amount": "100.00",
            "currency": "SIM",
            "payer_wallet_id": payer_wid,
        },
        headers={"X-API-Key": key},
    )
    assert inv.status_code == 201
    iid = inv.json()["data"]["id"]

    ar = await client_phase4.post(
        f"/api/v1/invoices/{iid}/approve",
        headers={"X-API-Key": key},
    )
    assert ar.status_code == 200

    # Bump exchange rate (later effective_at so get_latest picks 1.05)
    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(
            """
            INSERT INTO exchange_rates (id, from_currency, to_currency, rate, effective_at)
            VALUES (?, 'SIM', 'SIM', 1.05, datetime('now', '+1 day'))
            """,
            (str(uuid.uuid4()),),
        )
        await conn.commit()
    finally:
        await conn.close()

    ex = await client_phase4.post(
        "/api/v1/payment-batches/execute",
        headers={"X-API-Key": key},
    )
    assert ex.status_code == 200
    assert ex.json()["data"]["processed"] == 1

    gr = await client_phase4.get(
        "/api/v1/settlements",
        headers={"X-API-Key": key},
        params={"format": "json", "page": 1, "limit": 10},
    )
    assert gr.status_code == 200
    row = gr.json()["data"][0]
    assert float(row["exchange_rate_used"]) == 1.05
    # PF-013: settled_amount used current batch rate on sum (105.00) vs nominal total (100.00)
    assert row["total_amount"] == "100.00"
    assert row["settled_amount"] == "105.00"


@pytest.mark.asyncio
async def test_pf016_csv_comma_in_name(client_phase4: AsyncClient, db_path) -> None:
    key, payer_wid = await _seed_admin_wallet(db_path)

    vr = await client_phase4.post(
        "/api/v1/vendors",
        json={
            "name": "Acme, LLC",
            "email": "x@y.com",
            "payment_terms": "immediate",
        },
        headers={"X-API-Key": key},
    )
    vendor_id = vr.json()["data"]["id"]
    inv = await client_phase4.post(
        "/api/v1/invoices",
        json={
            "vendor_id": vendor_id,
            "invoice_number": "INV-CSV",
            "amount": "10.00",
            "payer_wallet_id": payer_wid,
        },
        headers={"X-API-Key": key},
    )
    iid = inv.json()["data"]["id"]
    await client_phase4.post(f"/api/v1/invoices/{iid}/approve", headers={"X-API-Key": key})
    await client_phase4.post("/api/v1/payment-batches/execute", headers={"X-API-Key": key})

    r = await client_phase4.get(
        "/api/v1/settlements",
        headers={"X-API-Key": key},
        params={"format": "csv"},
    )
    assert r.status_code == 200
    text = r.text
    # PF-016: extra comma from unquoted vendor name breaks columns
    assert text.count(",") > 4


@pytest.mark.asyncio
async def test_pf015_deleted_vendor_batch_typeerror(client_phase4: AsyncClient, db_path) -> None:
    key, payer_wid = await _seed_admin_wallet(db_path)

    vr = await client_phase4.post(
        "/api/v1/vendors",
        json={"name": "DelCo", "email": "d@d.io", "payment_terms": "immediate"},
        headers={"X-API-Key": key},
    )
    vid = vr.json()["data"]["id"]
    inv = await client_phase4.post(
        "/api/v1/invoices",
        json={
            "vendor_id": vid,
            "invoice_number": "INV-DEL",
            "amount": "5.00",
            "payer_wallet_id": payer_wid,
        },
        headers={"X-API-Key": key},
    )
    iid = inv.json()["data"]["id"]
    await client_phase4.post(f"/api/v1/invoices/{iid}/approve", headers={"X-API-Key": key})

    await client_phase4.delete(f"/api/v1/vendors/{vid}", headers={"X-API-Key": key})

    # PF-015: None vendor row → TypeError propagates through ASGI
    with pytest.raises(TypeError):
        await client_phase4.post(
            "/api/v1/payment-batches/execute",
            headers={"X-API-Key": key},
        )
