from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

from app.api.webhook import router as webhook_router
from app.jobs.inactivity_reminders import run_inactivity_reminders_job
from app.api.panel_sessions import router as panel_sessions_router
from app.api.panel_messages import router as panel_messages_router

app = FastAPI(title="MXCOMP Chatbot")
app.include_router(webhook_router)
app.include_router(panel_sessions_router)
app.include_router(panel_messages_router)

scheduler = BackgroundScheduler(timezone="UTC")


@app.on_event("startup")
def startup():
    scheduler.add_job(
        run_inactivity_reminders_job,
        "interval",
        seconds=30,  # ajusta si quieres
        id="inactivity_reminders",
        max_instances=1,  # solo dentro del mismo proceso
        coalesce=True,
    )
    scheduler.start()


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/")
def health():
    return {"status": "ok"}