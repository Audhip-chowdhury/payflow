"""Load dev seed users + wallets (10_000.00 SIM each). Run: python -m payflow.seed"""

from __future__ import annotations

import asyncio
import secrets
import uuid

import aiosqlite

from payflow.config import get_settings
from payflow.migrations_runner import run_alembic_upgrade

PAISE_10K = 1_000_000  # 10000.00 SIM
# Company float for expense reimbursements (matches default REIMBURSEMENT_WALLET_ID)
COMPANY_USER_ID = "00000000-0000-4000-8000-0000000000b0"
COMPANY_WALLET_ID = "00000000-0000-4000-8000-0000000000c0"
PAISE_COMPANY_FLOAT = 1_000_000_000  # 10_000_000.00 SIM

SEED_CATEGORIES: list[tuple[str, str, int | None]] = [
    ("00000000-0000-4000-8000-00000000ca01", "Travel", 1_000_000),
    ("00000000-0000-4000-8000-00000000ca02", "Meals & Entertainment", 500_000),
    ("00000000-0000-4000-8000-00000000ca03", "Office Supplies", 200_000),
    ("00000000-0000-4000-8000-00000000ca04", "Software & Tools", None),
    ("00000000-0000-4000-8000-00000000ca05", "Training", 2_500_000),
]

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

        cu = await conn.execute(
            "SELECT id FROM users WHERE id = ?", (COMPANY_USER_ID,)
        )
        if not await cu.fetchone():
            cur = await conn.execute("SELECT datetime('now')")
            now = (await cur.fetchone())[0]
            await conn.execute(
                """
                INSERT INTO users (id, username, email, api_key, role, is_active, created_at, updated_at)
                VALUES (?, 'company', 'company@simcorp.internal', 'pfk_company_float_dev_only', 'admin', 1, ?, ?)
                """,
                (COMPANY_USER_ID, now, now),
            )
            await conn.execute(
                """
                INSERT INTO wallets (id, user_id, currency, balance, status, created_at, updated_at)
                VALUES (?, ?, 'SIM', ?, 'active', ?, ?)
                """,
                (COMPANY_WALLET_ID, COMPANY_USER_ID, PAISE_COMPANY_FLOAT, now, now),
            )
            lines.append(
                f"company float wallet: {COMPANY_WALLET_ID} (set REIMBURSEMENT_WALLET_ID if needed)"
            )
        else:
            lines.append("skip company float user")

        for cid, cname, plim in SEED_CATEGORIES:
            ex = await conn.execute(
                "SELECT id FROM expense_categories WHERE name = ?", (cname,)
            )
            if await ex.fetchone():
                continue
            await conn.execute(
                """
                INSERT INTO expense_categories (id, name, policy_limit, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (cid, cname, plim),
            )
            lines.append(f"category: {cname}")

        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='exchange_rates'"
        )
        if await cur.fetchone():
            er = await conn.execute(
                """
                SELECT id FROM exchange_rates
                WHERE from_currency = 'SIM' AND to_currency = 'SIM'
                LIMIT 1
                """
            )
            if not await er.fetchone():
                await conn.execute(
                    """
                    INSERT INTO exchange_rates (id, from_currency, to_currency, rate, effective_at)
                    VALUES (?, 'SIM', 'SIM', 1.0, datetime('now'))
                    """,
                    (str(uuid.uuid4()),),
                )
                lines.append("exchange_rates: SIM/SIM = 1.0")

        await conn.commit()
    finally:
        await conn.close()

    for line in lines:
        print(line)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
