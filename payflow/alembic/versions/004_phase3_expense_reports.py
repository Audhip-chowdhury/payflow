"""Expense categories, reports, line items (Phase 3).

Revision ID: 004_phase3_expense_reports
Revises: 003_phase2_scheduled_webhooks
Create Date: Phase 3

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004_phase3_expense_reports"
down_revision: Union[str, None] = "003_phase2_scheduled_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE expense_categories (
            id TEXT PRIMARY KEY NOT NULL,
            name VARCHAR(100) NOT NULL UNIQUE,
            policy_limit INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
        );
    """)
    op.execute("""
        CREATE TABLE expense_reports (
            id TEXT PRIMARY KEY NOT NULL,
            submitter_id TEXT NOT NULL REFERENCES users(id),
            title VARCHAR(200) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN (
                    'draft', 'submitted', 'under_review', 'approved', 'rejected',
                    'reimbursed', 'cancelled'
                )),
            total_amount INTEGER NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
            currency VARCHAR(10) NOT NULL DEFAULT 'SIM',
            submitted_at TEXT,
            reviewed_by TEXT REFERENCES users(id),
            reviewed_at TEXT,
            rejection_reason TEXT,
            requires_multi_level INTEGER NOT NULL DEFAULT 0 CHECK (requires_multi_level IN (0, 1)),
            multi_level_threshold INTEGER NOT NULL DEFAULT 5000000,
            second_reviewer_id TEXT REFERENCES users(id),
            second_reviewed_at TEXT,
            reimbursement_transaction_id TEXT REFERENCES transactions(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute(
        "CREATE INDEX idx_expense_submitter ON expense_reports(submitter_id, status);"
    )
    op.execute("""
        CREATE TABLE expense_line_items (
            id TEXT PRIMARY KEY NOT NULL,
            expense_report_id TEXT NOT NULL REFERENCES expense_reports(id) ON DELETE CASCADE,
            category_id TEXT NOT NULL REFERENCES expense_categories(id),
            description TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            receipt_url TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expense_line_items;")
    op.execute("DROP INDEX IF EXISTS idx_expense_submitter;")
    op.execute("DROP TABLE IF EXISTS expense_reports;")
    op.execute("DROP TABLE IF EXISTS expense_categories;")
