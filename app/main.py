from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from app.api.panel_send import router as panel_send_router

from app.api.webhook import router as webhook_router
from app.jobs.inactivity_reminders import run_inactivity_reminders_job
from fastapi.staticfiles import StaticFiles

from app.router.panel_router import router as panel_router


from fastapi.middleware.cors import CORSMiddleware



app = FastAPI(title="MXCOMP Chatbot")
app.include_router(webhook_router)
app.include_router(panel_router)
app.include_router(panel_send_router)
app.mount("/panel", StaticFiles(directory="panel", html=True), name="panel")

scheduler = BackgroundScheduler(timezone="UTC")



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",  # tu frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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