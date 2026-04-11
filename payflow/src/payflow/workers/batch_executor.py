"""Background batch payment executor (Phase 4)."""

from __future__ import annotations

from loguru import logger

from payflow.database import transaction_immediate
from payflow.services import payment_batch_service


async def run_due_invoice_batch_tick() -> None:
    """Pay approved invoices that are due (same rules as POST execute)."""
    try:
        async with transaction_immediate() as conn:
            out = await payment_batch_service.execute_batch_worker(conn)
        if out.get("processed", 0) or out.get("failed", 0):
            logger.info("Invoice batch tick: {}", out)
    except TypeError as e:
        # PF-015: deleted vendor can surface as None dereference
        logger.exception("Invoice batch tick failed: {}", e)
        raise
