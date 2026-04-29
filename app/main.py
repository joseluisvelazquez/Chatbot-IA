from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

from app.api.webhook import router as webhook_router

from app.config.paths import MEDIA_DIR, PANEL_DIR
from app.jobs.inactivity_reminders import run_inactivity_reminders_job
from fastapi.staticfiles import StaticFiles
from app.router.auth_router import router as auth_router
from app.router.panel_router import router as panel_router
from app.router.media_router import router as media_router




from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.external import router as external_router



app = FastAPI(title="MXCOMP Chatbot")
app.include_router(webhook_router)
app.include_router(panel_router)
app.include_router(media_router)
app.include_router(auth_router)  
app.include_router(external_router)

app.mount("/panel", StaticFiles(directory="panel", html=True), name="panel")

app.mount("/media", StaticFiles(directory="/app/media"), name="media")

scheduler = BackgroundScheduler(timezone="UTC")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://192.168.50.61:5500",
        "http://192.168.50.165:5500",
        "http://192.168.1.106:5500",
        "http://192.168.1.71:5500",
        "http://192.168.50.191:5500"
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
