"""Environment configuration (single source of truth for paths and URLs)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: Path = Field(
        default=Path("data/payflow.db"),
        description="SQLite database file path (app + Alembic).",
    )
    host: str = Field(default="127.0.0.1", validation_alias="HOST")
    port: int = Field(default=3000, validation_alias="PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # Hot reload when using python -m payflow.main or uvicorn with matching settings.
    reload: bool = Field(default=True, validation_alias="RELOAD")

    # Comma-separated list, or "*" for any origin (local dev / Swagger "Try it out").
    cors_origins: str = Field(default="*", validation_alias="CORS_ORIGINS")

    enable_worker: bool = Field(default=True, validation_alias="ENABLE_WORKER")
    worker_interval_seconds: int = Field(default=60, validation_alias="WORKER_INTERVAL_SECONDS")

    # Company float wallet for expense reimbursements (must exist in DB; see seed).
    reimbursement_wallet_id: str = Field(
        default="00000000-0000-4000-8000-0000000000c0",
        validation_alias="REIMBURSEMENT_WALLET_ID",
    )

    enable_batch_worker: bool = Field(default=True, validation_alias="ENABLE_BATCH_WORKER")
    batch_worker_interval_seconds: int = Field(
        default=120,
        validation_alias="BATCH_WORKER_INTERVAL_SECONDS",
    )

    # Phase 5 — rate limits (in-process; high defaults for dev/tests).
    rate_limit_transfers_per_wallet_per_minute: int = Field(
        default=1000,
        validation_alias="RATE_LIMIT_TRANSFERS_PER_WALLET_PER_MINUTE",
    )
    rate_limit_window_minutes: int = Field(
        default=1,
        validation_alias="RATE_LIMIT_WINDOW_MINUTES",
    )
    rate_limit_wallet_creates_per_user_per_hour: int = Field(
        default=1000,
        validation_alias="RATE_LIMIT_WALLET_CREATES_PER_USER_PER_HOUR",
    )

    @property
    def sync_database_url(self) -> str:
        """SQLAlchemy/Alembic sync URL for the same SQLite file as the app."""
        resolved = self.database_path.resolve()
        return f"sqlite:///{resolved.as_posix()}"

    def cors_allow_origins(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
