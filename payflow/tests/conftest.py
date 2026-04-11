"""Shared fixtures — isolated SQLite DB + httpx async client."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from payflow.config import get_settings
from payflow.main import create_app
from payflow.migrations_runner import run_alembic_upgrade

TEST_API_KEY = "pfk_test_secret_key_phase0"


@pytest.fixture(autouse=True)
def _disable_background_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """APScheduler must not run during pytest (isolated DB + no side effects)."""
    monkeypatch.setenv("ENABLE_WORKER", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def insert_user_and_wallet(
    db_path: Path,
    *,
    username: str,
    email: str,
    api_key: str,
    role: str = "employee",
    balance_paise: int = 0,
    is_active: int = 1,
) -> tuple[str, str]:
    """Insert user + one SIM wallet; returns (user_id, wallet_id)."""
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, username, email, api_key, role, is_active, now, now),
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


async def insert_user_only(
    db_path: Path,
    *,
    username: str,
    email: str,
    api_key: str,
    role: str = "employee",
    is_active: int = 1,
) -> str:
    """User row only (no wallet)."""
    uid = str(uuid.uuid4())
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        cur = await conn.execute("SELECT datetime('now')")
        now = (await cur.fetchone())[0]
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, username, email, api_key, role, is_active, now, now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return uid


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temporary DB file; DATABASE_PATH env + clear settings cache."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
async def async_client(db_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client — schema applied before requests (httpx ASGITransport has no lifespan kw)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def async_client_with_user(db_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """Client with one seeded user (for /api/v1/me)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(
            """
            INSERT INTO users (id, username, email, api_key, role, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                "alice",
                "alice@test.example",
                TEST_API_KEY,
                "admin",
                1,
            ),
        )
        await conn.commit()
    finally:
        await conn.close()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def async_client_with_wallet(
    db_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, str, str], None]:
    """Client, API key, wallet_id for one user with 1_000_000 paise (10_000.00 SIM)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    key = "pfk_wallet_user"
    _, wid = await insert_user_and_wallet(
        db_path,
        username="wuser",
        email="w@example.com",
        api_key=key,
        balance_paise=1_000_000,
    )
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, key, wid
