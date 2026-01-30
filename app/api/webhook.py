from fastapi import APIRouter
from app.models.message import IncomingMessage
from app.services.flow_engine import process_message
from app.services.session_service import get_or_create_session, update_session
from app.core.states import ChatState

router = APIRouter()

@router.post("/webhook")
def webhook(payload: IncomingMessage):
    # ⚠️ Simulado por ahora
    phone = "5214420000000"

    session = get_or_create_session(phone)

    reply, next_state, buttons = process_message(
        ChatState(session.state),
        text=payload.text,
        button_id=payload.button_id,
    )

    update_session(session.id, next_state, payload.text)

    return {
        "reply": reply,
        "next_state": next_state,
        "buttons": buttons,
    }
