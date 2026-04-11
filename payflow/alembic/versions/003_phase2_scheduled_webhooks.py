"""Scheduled / recurring payments and webhooks (Phase 2).

Revision ID: 003_phase2_scheduled_webhooks
Revises: 002_phase1_wallets_transfers
Create Date: Phase 2

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "003_phase2_scheduled_webhooks"
down_revision: Union[str, None] = "002_phase1_wallets_transfers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE scheduled_payments (
            id TEXT PRIMARY KEY NOT NULL,
            sender_wallet_id TEXT NOT NULL REFERENCES wallets(id),
            receiver_wallet_id TEXT NOT NULL REFERENCES wallets(id),
            amount INTEGER NOT NULL CHECK (amount > 0),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            description TEXT,
            scheduled_date TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'executed', 'failed', 'cancelled')),
            executed_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_scheduled_pending ON scheduled_payments(scheduled_date, status) "
        "WHERE status = 'pending';"
    )

    op.execute("""
        CREATE TABLE recurring_payments (
            id TEXT PRIMARY KEY NOT NULL,
            sender_wallet_id TEXT NOT NULL REFERENCES wallets(id),
            receiver_wallet_id TEXT NOT NULL REFERENCES wallets(id),
            amount INTEGER NOT NULL CHECK (amount > 0),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            description TEXT,
            frequency VARCHAR(20) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
            day_of_month INTEGER CHECK (day_of_month BETWEEN 1 AND 31),
            day_of_week INTEGER CHECK (day_of_week BETWEEN 0 AND 6),
            next_execution_date TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'cancelled')),
            start_date TEXT NOT NULL,
            end_date TEXT,
            total_executions INTEGER NOT NULL DEFAULT 0,
            last_executed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_recurring_active ON recurring_payments(next_execution_date, status) "
        "WHERE status = 'active';"
    )

    op.execute("""
        CREATE TABLE webhook_subscriptions (
            id TEXT PRIMARY KEY NOT NULL,
            user_id TEXT NOT NULL REFERENCES users(id),
            url TEXT NOT NULL,
            events TEXT NOT NULL,
            secret VARCHAR(64) NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    op.execute("""
        CREATE TABLE webhook_deliveries (
            id TEXT PRIMARY KEY NOT NULL,
            subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(id),
            event_type VARCHAR(50) NOT NULL,
            payload TEXT NOT NULL,
            response_status INTEGER,
            response_body TEXT,
            attempt INTEGER NOT NULL DEFAULT 1,
            delivered_at TEXT,
            next_retry_at TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'delivered', 'failed', 'retrying')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_deliveries;")
    op.execute("DROP TABLE IF EXISTS webhook_subscriptions;")
    op.execute("DROP INDEX IF EXISTS idx_recurring_active;")
    op.execute("DROP TABLE IF EXISTS recurring_payments;")
    op.execute("DROP INDEX IF EXISTS idx_scheduled_pending;")
    op.execute("DROP TABLE IF EXISTS scheduled_payments;")
