"""Run Alembic upgrades programmatically (e.g. on app startup)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from payflow.config import get_settings


def project_root() -> Path:
    """Repository root (directory containing alembic.ini)."""
    # src/payflow/migrations_runner.py -> parents[2] = payflow project root
    return Path(__file__).resolve().parents[2]


def run_alembic_upgrade() -> None:
    """Apply all pending migrations to head."""
    get_settings().database_path.parent.mkdir(parents=True, exist_ok=True)
    root = project_root()
    ini_path = root / "alembic.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(f"alembic.ini not found at {ini_path}")

    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
    command.upgrade(cfg, "head")
