"""Fraud rules, flagged transactions, immutable audit log (Phase 5).

Revision ID: 006_phase5_fraud_audit
Revises: 005_phase4_vendors_invoices
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "006_phase5_fraud_audit"
down_revision: Union[str, None] = "005_phase4_vendors_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fraud_rules (
            id TEXT PRIMARY KEY NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            rule_type VARCHAR(30) NOT NULL
                CHECK (rule_type IN ('velocity', 'amount_threshold', 'geo_anomaly', 'pattern')),
            config TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            action VARCHAR(20) NOT NULL DEFAULT 'flag'
                CHECK (action IN ('flag', 'block', 'alert')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("""
        CREATE TABLE flagged_transactions (
            id TEXT PRIMARY KEY NOT NULL,
            transaction_id TEXT NOT NULL REFERENCES transactions(id),
            rule_id TEXT NOT NULL REFERENCES fraud_rules(id),
            reason TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'released', 'blocked', 'escalated')),
            reviewed_by TEXT REFERENCES users(id),
            reviewed_at TEXT,
            review_notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_flagged_pending ON flagged_transactions(status) "
        "WHERE status = 'pending';"
    )
    op.execute(
        "CREATE INDEX idx_flagged_tx ON flagged_transactions(transaction_id);"
    )

    op.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            entity_type VARCHAR(50) NOT NULL,
            entity_id TEXT NOT NULL,
            action VARCHAR(50) NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            changes TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            error_message TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_audit_actor ON audit_log(actor_id, created_at DESC);"
    )

    op.execute("""
        CREATE TRIGGER audit_log_immutable_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is immutable');
        END;
    """)
    op.execute("""
        CREATE TRIGGER audit_log_immutable_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is immutable');
        END;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutable_delete;")
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutable_update;")
    op.execute("DROP INDEX IF EXISTS idx_audit_actor;")
    op.execute("DROP INDEX IF EXISTS idx_audit_entity;")
    op.execute("DROP TABLE IF EXISTS audit_log;")
    op.execute("DROP INDEX IF EXISTS idx_flagged_tx;")
    op.execute("DROP INDEX IF EXISTS idx_flagged_pending;")
    op.execute("DROP TABLE IF EXISTS flagged_transactions;")
    op.execute("DROP TABLE IF EXISTS fraud_rules;")
