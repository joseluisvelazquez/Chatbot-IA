from fastapi import FastAPI
from app.api.webhook import router as webhook_router

app = FastAPI(title="MXCOMP Chatbot")

app.include_router(webhook_router)


@app.get("/")
def health():
    return {"status": "ok"}
