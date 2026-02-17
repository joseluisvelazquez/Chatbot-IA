from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.utils.restart_detector import wants_restart
from app.db.session import get_db
from app.adapters.meta_webhook import parse_meta_message
from app.services.session_service import get_or_create_session, update_session
from app.adapters.whatsapp_client import send_whatsapp_message
from app.core.flow_engine import process_message
from app.core.states import ChatState
from app.core.flow import FLOW
import os

router = APIRouter()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

def is_test_payload(payload: dict) -> bool:
    return "phone" in payload and "text" in payload

# ---------------- VERIFY ----------------
@router.get("/webhook")
async def verify(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))

    return PlainTextResponse("Error", status_code=403)


# ---------------- RECEIVE ----------------
@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):

    payload = await request.json()
    # ---------------- TEST MODE ----------------
    if is_test_payload(payload):
        phone = payload["phone"]
        text = payload["text"]
        button_id = payload.get("button_id")
        message_id = payload.get("message_id")

        chat = get_or_create_session(db, phone)

        reply, next_state, buttons, prev, document = process_message(
            state=chat.state,
            text=text,
            intent=button_id,
            previous_state=chat.previous_state,
        )

        update_session(
            db=db,
            session=chat,
            state=next_state.value,
            last_message=text,
            previous_state=prev,
            message_id=message_id,
        )

        return {
            "reply": reply,
            "next_state": next_state.value,
            "buttons": buttons,
        }
    
    data = parse_meta_message(payload)

    if not data:
        return {"status": "ignored"}

    phone = data["phone"]
    text = data["text"]
    message_id = data["message_id"]
    button_id = data["button_id"]

    reply = None
    buttons = []

    try:
        # 🔒 BLOQUEO DE SESIÓN (FOR UPDATE vive dentro del service)
        chat = get_or_create_session(db, phone)

        # 🚫 Anti duplicado DENTRO de la transacción
        if chat.last_message_id == message_id: # Si el último mensaje procesado es el mismo que estamos recibiendo, es un duplicado. Esto puede pasar si Meta reintenta enviar el mismo mensaje varias veces.
            db.rollback()
            return {"status": "duplicate"}

        # 🔄 RESTART GLOBAL
        if wants_restart(text): #No se subira a producción esta función, es solo para pruebas internas, y se puede activar escribiendo "reiniciar" o "restart" en el chat.
            next_state = ChatState.INICIO
            flow = FLOW[next_state]

            update_session(
                session=chat,
                state=next_state.value,
                last_message=text,
                previous_state=None,
                message_id=message_id,
            )

            reply = "Perfecto 👍 reiniciemos tu proceso.\n\n" + flow["text"]
            buttons = flow.get("buttons", [])

        # 💤 Primer mensaje después de espera
        elif chat.state == ChatState.ESPERA.value:
            next_state = ChatState.INICIO
            flow = FLOW[next_state]

            update_session(
                session=chat,
                state=next_state.value,
                last_message=text,
                previous_state=None,
                message_id=message_id,
            )

            reply = flow["text"]
            buttons = flow.get("buttons", [])

        # 🔁 Flujo normal
        else:
            reply, next_state, buttons, prev, document = process_message(
                state=chat.state,
                text=text,
                intent=button_id,
                previous_state=chat.previous_state,
            )

            update_session(
                session=chat,
                state=next_state.value,
                last_message=text,
                previous_state=prev,
                message_id=message_id,
            )

        # 🔴 EL ÚNICO COMMIT DEL REQUEST
        db.commit() ##Se utiliza commit aquí para asegurar que el lock se libere lo antes posible, y que los cambios en la sesión se guarden solo después de procesar el mensaje exitosamente.

    except Exception as e:
        db.rollback()
        raise e

    # 📤 RESPONDER FUERA DEL LOCK
    if reply:
        await send_whatsapp_message(phone, reply, buttons) # Se responde al usuario después de liberar el lock, para minimizar el tiempo que la sesión está bloqueada.
        
    return {"status": "ok"}
