"""Load dev seed users + wallets (10_000.00 SIM each). Run: python -m payflow.seed"""

from __future__ import annotations

import asyncio
import secrets
import uuid

import aiosqlite

from payflow.config import get_settings
from payflow.migrations_runner import run_alembic_upgrade

PAISE_10K = 1_000_000  # 10000.00 SIM

SEED_USERS = [
    ("alice", "alice@simcorp.io", "admin"),
    ("bob", "bob@simcorp.io", "manager"),
    ("charlie", "charlie@simcorp.io", "employee"),
    ("diana", "diana@simcorp.io", "employee"),
    ("eve", "eve@simcorp.io", "employee"),
]


async def run() -> None:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()

    conn = await aiosqlite.connect(settings.database_path)
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA journal_mode=WAL")

        lines: list[str] = []
        for username, email, role in SEED_USERS:
            exists = await conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            )
            row = await exists.fetchone()
            if row:
                lines.append(f"skip existing user {username}")
                continue

            uid = str(uuid.uuid4())
            api_key = "pfk_" + secrets.token_hex(24)
            cur = await conn.execute("SELECT datetime('now')")
            now = (await cur.fetchone())[0]
            await conn.execute(
                """
                INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (uid, username, email, api_key, role, now, now),
            )

            wid = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
                VALUES (?, ?, 'SIM', ?, 'active', ?, ?)
                """,
                (wid, uid, PAISE_10K, now, now),
            )
            lines.append(f"{username}: api_key={api_key}")

        await conn.commit()
    finally:
        await conn.close()

    for line in lines:
        print(line)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
