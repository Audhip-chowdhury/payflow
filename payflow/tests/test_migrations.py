"""Alembic upgrades are idempotent."""

from __future__ import annotations

from pathlib import Path

import pytest

from payflow.migrations_runner import run_alembic_upgrade


def test_alembic_upgrade_idempotent(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    from payflow.config import get_settings as gs

    gs.cache_clear()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_alembic_upgrade()
    run_alembic_upgrade()
    gs.cache_clear()
