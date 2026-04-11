"""Background tick: execute due scheduled + recurring payments."""

from __future__ import annotations

from datetime import date

import aiosqlite
from loguru import logger

from payflow.database import fetch_all, fetch_one, transaction_immediate
from payflow.exceptions import AppError
from payflow.services import scheduler_service, webhook_service
from payflow.services.transfer_service import transfer_funds_atomic


async def _sender_user_id(conn: aiosqlite.Connection, wallet_id: str) -> str:
    row = await fetch_one(
        conn,
        "SELECT user_id FROM wallets WHERE id = ?",
        (wallet_id,),
    )
    assert row is not None
    return str(row["user_id"])


async def process_scheduled_payment(schedule_id: str) -> None:
    today = date.today().isoformat()
    async with transaction_immediate() as conn:
        row = await fetch_one(
            conn,
            "SELECT * FROM scheduled_payments WHERE id = ?",
            (schedule_id,),
        )
        if row is None or row["status"] != "pending":
            return
        if row["scheduled_date"] > today:
            return

        amount = int(row["amount"])
        desc = row["description"]
        try:
            data = await transfer_funds_atomic(
                conn,
                sender_wallet_id=row["sender_wallet_id"],
                receiver_wallet_id=row["receiver_wallet_id"],
                amount_paise=amount,
                description=desc,
                reference_type="scheduled_payment",
                reference_id=schedule_id,
            )
            await conn.execute(
                """
                UPDATE scheduled_payments SET
                  status = 'executed',
                  executed_at = datetime('now'),
                  updated_at = datetime('now')
                WHERE id = ?
                """,
                (schedule_id,),
            )
            uid = await _sender_user_id(conn, row["sender_wallet_id"])
        except AppError as e:
            msg = e.message
            code = e.code
            await conn.execute(
                """
                UPDATE scheduled_payments SET
                  status = 'failed',
                  error_message = ?,
                  executed_at = datetime('now'),
                  updated_at = datetime('now')
                WHERE id = ?
                """,
                (msg, schedule_id),
            )
            uid = await _sender_user_id(conn, row["sender_wallet_id"])
            await webhook_service.notify_user_event(
                uid,
                "payment.failed",
                {
                    "reason": code,
                    "message": msg,
                    "scheduled_payment_id": schedule_id,
                },
            )
            return

    await webhook_service.notify_user_event(
        uid,
        "payment.executed",
        {
            "transaction_id": data["transaction_id"],
            "amount": data["amount"],
            "sender_wallet_id": data["sender_wallet_id"],
            "receiver_wallet_id": data["receiver_wallet_id"],
            "scheduled_payment_id": schedule_id,
        },
    )


async def process_recurring_payment(rid: str) -> None:
    today = date.today().isoformat()
    async with transaction_immediate() as conn:
        row = await fetch_one(
            conn,
            "SELECT * FROM recurring_payments WHERE id = ?",
            (rid,),
        )
        if row is None or row["status"] != "active":
            return
        if row["next_execution_date"] > today:
            return
        if row["end_date"] and row["end_date"] < today:
            await conn.execute(
                """
                UPDATE recurring_payments SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?
                """,
                (rid,),
            )
            return

        amount = int(row["amount"])
        desc = row["description"]
        freq = row["frequency"]
        dom = row["day_of_month"]
        dow = row["day_of_week"]
        try:
            data = await transfer_funds_atomic(
                conn,
                sender_wallet_id=row["sender_wallet_id"],
                receiver_wallet_id=row["receiver_wallet_id"],
                amount_paise=amount,
                description=desc,
                reference_type="recurring_payment",
                reference_id=rid,
            )
            last_run = date.fromisoformat(row["next_execution_date"])
            next_d = scheduler_service.advance_next_execution(
                last_run,
                freq,
                int(dom) if dom is not None else None,
                int(dow) if dow is not None else None,
            )
            end_dt = date.fromisoformat(row["end_date"]) if row["end_date"] else None
            if end_dt is not None and next_d > end_dt:
                new_status = "cancelled"
            else:
                new_status = "active"

            await conn.execute(
                """
                UPDATE recurring_payments SET
                  next_execution_date = ?,
                  total_executions = total_executions + 1,
                  last_executed_at = datetime('now'),
                  status = ?,
                  updated_at = datetime('now')
                WHERE id = ?
                """,
                (next_d.isoformat(), new_status, rid),
            )
            uid = await _sender_user_id(conn, row["sender_wallet_id"])
        except AppError as e:
            msg = e.message
            code = e.code
            await conn.execute(
                """
                UPDATE recurring_payments SET
                  status = 'failed',
                  updated_at = datetime('now')
                WHERE id = ?
                """,
                (rid,),
            )
            uid = await _sender_user_id(conn, row["sender_wallet_id"])
            await webhook_service.notify_user_event(
                uid,
                "payment.failed",
                {
                    "reason": code,
                    "message": msg,
                    "recurring_payment_id": rid,
                },
            )
            return

    await webhook_service.notify_user_event(
        uid,
        "payment.executed",
        {
            "transaction_id": data["transaction_id"],
            "amount": data["amount"],
            "sender_wallet_id": data["sender_wallet_id"],
            "receiver_wallet_id": data["receiver_wallet_id"],
            "recurring_payment_id": rid,
        },
    )


async def run_due_payment_tick() -> None:
    today = date.today().isoformat()
    from payflow.database import get_connection

    async with get_connection() as conn:
        scheduled = await fetch_all(
            conn,
            """
            SELECT id FROM scheduled_payments
            WHERE status = 'pending' AND scheduled_date <= ?
            """,
            (today,),
        )
        recurring = await fetch_all(
            conn,
            """
            SELECT id FROM recurring_payments
            WHERE status = 'active' AND next_execution_date <= ?
            """,
            (today,),
        )

    for r in scheduled:
        try:
            await process_scheduled_payment(str(r["id"]))
        except Exception as e:
            logger.exception("scheduled payment {}: {}", r["id"], e)

    for r in recurring:
        try:
            await process_recurring_payment(str(r["id"]))
        except Exception as e:
            logger.exception("recurring payment {}: {}", r["id"], e)
