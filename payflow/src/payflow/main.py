"""Application entry — FastAPI app factory and CLI run."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from payflow.config import get_settings
from payflow.middleware.error_handler import register_exception_handlers
from payflow.migrations_runner import run_alembic_upgrade
from payflow.routers import (
    expense_reports,
    health,
    invoices,
    me,
    payment_batches,
    recurring_payments,
    scheduled_payments,
    settlements,
    transactions,
    transfers,
    vendors,
    wallets,
    webhooks,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Running database migrations…")
    run_alembic_upgrade()
    logger.info("Migrations complete.")

    scheduler = None
    if settings.enable_worker or settings.enable_batch_worker:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        if settings.enable_worker:
            from payflow.workers.payment_executor import run_due_payment_tick

            scheduler.add_job(
                run_due_payment_tick,
                "interval",
                seconds=max(1, settings.worker_interval_seconds),
                id="payment_executor",
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Payment executor: every {}s (ENABLE_WORKER=true)",
                settings.worker_interval_seconds,
            )
        if settings.enable_batch_worker:
            from payflow.workers.batch_executor import run_due_invoice_batch_tick

            scheduler.add_job(
                run_due_invoice_batch_tick,
                "interval",
                seconds=max(1, settings.batch_worker_interval_seconds),
                id="invoice_batch_executor",
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Invoice batch executor: every {}s (ENABLE_BATCH_WORKER=true)",
                settings.batch_worker_interval_seconds,
            )
        scheduler.start()

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PayFlow",
        version="0.1.0",
        lifespan=lifespan,
    )
    origins = settings.cors_allow_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False if origins == ["*"] else True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(wallets.router)
    app.include_router(transfers.router)
    app.include_router(transactions.router)
    app.include_router(scheduled_payments.router)
    app.include_router(recurring_payments.router)
    app.include_router(webhooks.router)
    app.include_router(expense_reports.router)
    app.include_router(vendors.router)
    app.include_router(invoices.router)
    app.include_router(payment_batches.router)
    app.include_router(settlements.router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
    )
    uvicorn.run(
        "payflow.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
