from fastapi import APIRouter
from app.schemas.webhook import WebhookRequest
from app.services.session_service import (
    get_or_create_session,
    update_session
)
from app.core.flow_engine import process_message 
from app.core.states import ChatState

router = APIRouter()

@router.post("/webhook")
def webhook(payload: WebhookRequest):

    phone = payload.phone
    current_state = ChatState(payload.state)
    text = payload.text
    button_id = payload.button_id

    # 1️⃣ Crear u obtener sesión
    session = get_or_create_session(phone)

    # 2️⃣ Procesar mensaje
    reply, next_state, buttons = process_message(
        state=current_state,
        text=text,
        button_id=button_id
    )

    # 3️⃣ Guardar estado y último mensaje
    update_session(
        session_id=session.id,   # 👈 AQUÍ ESTÁ LA CLAVE
        state=next_state,
        last_message=text
    )


    # 4️⃣ Responder
    return {
        "reply": reply,
        "next_state": next_state.value,
        "buttons": buttons,
    }
