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
    data = parse_meta_message(payload)

    if not data:
        return {"status": "ignored"}

    phone = data["phone"]
    text = data["text"]
    message_id = data["message_id"]
    button_id = data["button_id"]
    next_state = ChatState.INICIO

    # 1️⃣ Obtener sesión
    chat = get_or_create_session(db, phone)

    # 🚫 2️⃣ Anti duplicado (SIEMPRE PRIMERO)
    if chat.last_message_id == message_id:
        return {"status": "duplicate"}

    # 🔄 3️⃣ RESTART GLOBAL
    if wants_restart(text):

        next_state = ChatState.INICIO
        flow = FLOW[next_state]

        update_session(
            db=db,
            session=chat,
            state=next_state.value,
            last_message=text,
            previous_state=None,
            message_id=message_id,
        )

        await send_whatsapp_message(
            phone,
            "Perfecto 👍 reiniciemos tu proceso.\n\n" + flow["text"],
            flow.get("buttons", []),
        )

        return {"status": "restarted"}

    if chat.state == ChatState.ESPERA.value:

        next_state = ChatState.INICIO
        flow = FLOW[next_state]

        update_session(
            db=db,
            session=chat,
            state=next_state.value,
            last_message=text,
            previous_state=None,
            message_id=message_id,
        )

        await send_whatsapp_message(phone, flow["text"], flow.get("buttons", []))

        return {"status": "conversation_started"}

    # 5️⃣ Flow normal
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

    if reply:
        await send_whatsapp_message(phone, reply, buttons)

    return {"status": "ok"}
