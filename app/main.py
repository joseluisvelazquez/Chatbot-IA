from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
import logging

from app.api.webhook import router as webhook_router

from app.config.paths import MEDIA_DIR, PANEL_DIR
from app.jobs.inactivity_reminders import run_inactivity_reminders_job
from app.jobs.payment_reminders import run_payment_reminders_job
from app.config.settings import settings
from fastapi.staticfiles import StaticFiles
from app.router.auth_router import router as auth_router
from app.router.panel_router import router as panel_router
from app.router.payment_reminders import router as payment_reminders_router
from app.router.media_router import router as media_router
from app.router.siga_bridge_router import router as siga_bridge_router




from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.external import router as external_router



app = FastAPI(title="MXCOMP Chatbot")
app.include_router(webhook_router)
app.include_router(panel_router)
app.include_router(payment_reminders_router)
app.include_router(media_router)
app.include_router(auth_router)  
app.include_router(siga_bridge_router)
app.include_router(external_router)

app.mount("/panel", StaticFiles(directory=str(PANEL_DIR), html=True), name="panel")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

scheduler = BackgroundScheduler(timezone="UTC")
logger = logging.getLogger(__name__)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://192.168.50.61:5500",
        "http://192.168.50.165:5500",
        "http://192.168.1.106:5500",
        "http://192.168.1.71:5500",
        "http://192.168.50.191:5500",
        "https://chatbot.mxcomp.com.mx",
        "https://chatbot.mxcomp.mx",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    logger.info("scheduler_startup_begin")
    scheduler.add_job(
        run_inactivity_reminders_job,
        "interval",
        seconds=30,  # ajusta si quieres
        id="inactivity_reminders",
        max_instances=1,  # solo dentro del mismo proceso
        coalesce=True,
        replace_existing=True,
    )
    if settings.PAYMENT_REMINDERS_ENABLED:
        interval_minutes = max(1, int(settings.PAYMENT_REMINDER_SCHEDULER_INTERVAL_MINUTES or 15))
        logger.info(
            "payment_reminders_scheduler_enabled",
            extra={
                "interval_minutes": interval_minutes,
                "dry_run": settings.PAYMENT_REMINDERS_DRY_RUN,
                "company_id": settings.PAYMENT_REMINDER_COMPANY_ID,
                "limit": settings.PAYMENT_REMINDER_SYNC_LIMIT,
            },
        )
        scheduler.add_job(
            run_payment_reminders_job,
            "interval",
            minutes=interval_minutes,
            id="payment_reminders",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),
        )
        logger.info(
            "payment_reminders_scheduler_registered",
            extra={
                "job_id": "payment_reminders",
                "next_run_time": "startup_immediate",
                "interval_minutes": interval_minutes,
            },
        )
    else:
        logger.info("payment_reminders_scheduler_disabled")
    if not scheduler.running:
        scheduler.start()
    else:
        logger.info("scheduler_already_running")
    logger.info("scheduler_startup_finished")


@app.on_event("shutdown")
def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/")
def health():
    return {"status": "ok"}
