"""Foundation: users table for API key auth.

Revision ID: 001_foundation_users
Revises:
Create Date: Phase 0

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "001_foundation_users"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY NOT NULL,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(255) NOT NULL UNIQUE,
            api_key VARCHAR(64) NOT NULL UNIQUE,
            role VARCHAR(20) NOT NULL DEFAULT 'employee'
                CHECK (role IN ('employee', 'manager', 'admin', 'vendor')),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    op.execute("CREATE INDEX idx_users_api_key ON users(api_key);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_api_key;")
    op.execute("DROP TABLE IF EXISTS users;")
