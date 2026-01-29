from fastapi import APIRouter
from app.models.message import IncomingMessage
from app.services.flow_engine import process_message

router = APIRouter()

@router.post("/webhook")
def webhook(payload: IncomingMessage):
    reply, next_state, buttons = process_message(
        payload.state,
        text=payload.text,
        button_id=payload.button_id,
    )

    return {
        "reply": reply,
        "next_state": next_state,
        "buttons": buttons,
    }
