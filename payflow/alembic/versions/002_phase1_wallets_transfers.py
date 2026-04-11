"""Wallets, transactions ledger, idempotency store (Phase 1).

Revision ID: 002_phase1_wallets_transfers
Revises: 001_foundation_users
Create Date: Phase 1

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "002_phase1_wallets_transfers"
down_revision: Union[str, None] = "001_foundation_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE wallets (
            id TEXT PRIMARY KEY NOT NULL,
            user_id TEXT NOT NULL REFERENCES users(id),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'frozen', 'closed')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("CREATE INDEX idx_wallets_user_id ON wallets(user_id);")
    op.execute(
        "CREATE UNIQUE INDEX idx_wallets_user_currency ON wallets(user_id, currency);"
    )

    op.execute("""
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY NOT NULL,
            type VARCHAR(20) NOT NULL
                CHECK (type IN ('transfer', 'credit', 'debit', 'refund', 'settlement')),
            status VARCHAR(20) NOT NULL DEFAULT 'completed'
                CHECK (status IN ('pending', 'completed', 'failed', 'held')),
            sender_wallet_id TEXT REFERENCES wallets(id),
            receiver_wallet_id TEXT REFERENCES wallets(id),
            amount INTEGER NOT NULL CHECK (amount > 0),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            reference_id TEXT,
            reference_type VARCHAR(30),
            description TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_transactions_sender ON transactions(sender_wallet_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_transactions_receiver ON transactions(receiver_wallet_id, created_at DESC);"
    )

    op.execute("""
        CREATE TABLE idempotency_store (
            key_hash VARCHAR(128) PRIMARY KEY NOT NULL,
            endpoint VARCHAR(100) NOT NULL,
            api_key_id TEXT NOT NULL REFERENCES users(id),
            request_payload_hash VARCHAR(128) NOT NULL,
            response_status INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL DEFAULT (datetime('now', '+24 hours'))
        );
    """)
    op.execute("CREATE INDEX idx_idempotency_expires ON idempotency_store(expires_at);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_idempotency_expires;")
    op.execute("DROP TABLE IF EXISTS idempotency_store;")
    op.execute("DROP INDEX IF EXISTS idx_transactions_receiver;")
    op.execute("DROP INDEX IF EXISTS idx_transactions_sender;")
    op.execute("DROP TABLE IF EXISTS transactions;")
    op.execute("DROP INDEX IF EXISTS idx_wallets_user_currency;")
    op.execute("DROP INDEX IF EXISTS idx_wallets_user_id;")
    op.execute("DROP TABLE IF EXISTS wallets;")
