import asyncio
import logging

from app.config.settings import settings
from app.db.session import SessionLocal
from app.services.payment_reminder_service import (
    run_due_payment_reminders,
    sync_payment_reminder_candidates,
)


logger = logging.getLogger(__name__)


async def _run_payment_reminders() -> None:
    db = SessionLocal()
    try:
        sync_result = await sync_payment_reminder_candidates(
            db,
            company_id=settings.PAYMENT_REMINDER_COMPANY_ID,
            limit=settings.PAYMENT_REMINDER_SYNC_LIMIT,
            dry_run=settings.PAYMENT_REMINDERS_DRY_RUN,
        )
        due_result = await run_due_payment_reminders(
            db,
            company_id=settings.PAYMENT_REMINDER_COMPANY_ID,
            limit=settings.PAYMENT_REMINDER_SYNC_LIMIT,
            dry_run=settings.PAYMENT_REMINDERS_DRY_RUN,
        )
        logger.info(
            "payment_reminders_job_finished",
            extra={
                "dry_run": settings.PAYMENT_REMINDERS_DRY_RUN,
                "synced": sync_result.get("synced"),
                "processed": due_result.get("processed"),
            },
        )
    finally:
        db.close()


def run_payment_reminders_job() -> None:
    if not settings.PAYMENT_REMINDERS_ENABLED:
        return
    asyncio.run(_run_payment_reminders())

