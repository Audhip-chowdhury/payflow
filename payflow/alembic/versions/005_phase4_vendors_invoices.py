"""Vendors, invoices, payment batches, exchange rates, settlements (Phase 4).

Revision ID: 005_phase4_vendors_invoices
Revises: 004_phase3_expense_reports
Create Date: Phase 4

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005_phase4_vendors_invoices"
down_revision: Union[str, None] = "004_phase3_expense_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE vendors (
            id TEXT PRIMARY KEY NOT NULL,
            name VARCHAR(200) NOT NULL,
            email VARCHAR(255) NOT NULL,
            tax_id VARCHAR(50),
            payment_terms VARCHAR(20) NOT NULL DEFAULT 'net_30'
                CHECK (payment_terms IN ('immediate', 'net_15', 'net_30', 'net_60')),
            wallet_id TEXT REFERENCES wallets(id),
            bank_details TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive', 'deleted')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("""
        CREATE TABLE payment_batches (
            id TEXT PRIMARY KEY NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
            total_amount INTEGER NOT NULL DEFAULT 0,
            total_invoices INTEGER NOT NULL DEFAULT 0,
            processed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            executed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("""
        CREATE TABLE exchange_rates (
            id TEXT PRIMARY KEY NOT NULL,
            from_currency VARCHAR(10) NOT NULL,
            to_currency VARCHAR(10) NOT NULL,
            rate REAL NOT NULL,
            effective_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_exchange_rates_lookup ON exchange_rates(from_currency, to_currency, effective_at DESC);"
    )
    op.execute("""
        CREATE TABLE invoices (
            id TEXT PRIMARY KEY NOT NULL,
            vendor_id TEXT NOT NULL REFERENCES vendors(id),
            invoice_number VARCHAR(50) NOT NULL UNIQUE,
            amount INTEGER NOT NULL CHECK (amount > 0),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            description TEXT,
            due_date TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'scheduled', 'paid', 'cancelled', 'overdue')),
            payer_wallet_id TEXT NOT NULL REFERENCES wallets(id),
            transaction_id TEXT REFERENCES transactions(id),
            batch_id TEXT REFERENCES payment_batches(id),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("CREATE INDEX idx_invoices_vendor ON invoices(vendor_id, status);")
    op.execute(
        "CREATE INDEX idx_invoices_due ON invoices(due_date, status) WHERE status IN ('pending', 'approved');"
    )
    op.execute("""
        CREATE TABLE settlements (
            id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT REFERENCES payment_batches(id),
            vendor_id TEXT NOT NULL REFERENCES vendors(id),
            total_amount INTEGER NOT NULL,
            currency VARCHAR(10) NOT NULL,
            exchange_rate_used REAL,
            settled_amount INTEGER NOT NULL,
            settled_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS settlements;")
    op.execute("DROP INDEX IF EXISTS idx_invoices_due;")
    op.execute("DROP INDEX IF EXISTS idx_invoices_vendor;")
    op.execute("DROP TABLE IF EXISTS invoices;")
    op.execute("DROP INDEX IF EXISTS idx_exchange_rates_lookup;")
    op.execute("DROP TABLE IF EXISTS exchange_rates;")
    op.execute("DROP TABLE IF EXISTS payment_batches;")
    op.execute("DROP TABLE IF EXISTS vendors;")
