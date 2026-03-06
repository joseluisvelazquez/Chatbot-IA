from fastapi import APIRouter, Depends, Request 
from fastapi.responses import PlainTextResponse 
from sqlalchemy.orm import Session 
from app.db.session import get_db
from app.adapters.meta_webhook import parse_meta_payload
from app.services.session_service import get_or_create_session, update_session
from app.adapters.whatsapp_client import send_whatsapp_message
from app.core.flow_engine import process_message
from app.config.settings import settings
import asyncio
import time
from app.services.inconsistencias_service import (
    open_or_patch_inconsistencia,
    close_open_inconsistencia,
)
from app.core.states import ChatState

router = APIRouter()


# ---------------- VERIFY ----------------
@router.get("/webhook")
async def verify(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))

    return PlainTextResponse("Error", status_code=403)


# ---------------- RECEIVE ----------------
@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):

    payload = await request.json()

    data = parse_meta_payload(payload)

    # después de data = parse_meta_payload(payload)

    if not data:
        return {"status": "ignored"}

    # Ignora statuses
    if data.get("is_status"):
        return {"status": "whatsapp_status"}

    # Si no hay texto ni botón, no es input válido del usuario
    if not data.get("text") and not data.get("button_id"):
        return {"status": "ignored_no_user_input"}

    # Unsupported (media, location, etc.)
    if data.get("unsupported"):
        await send_whatsapp_message(
            data["phone"], "Por favor responde usando las opciones del menú 🙂"
        )
        return {"status": "ok"}

    phone = data["phone"]
    text = data["text"]
    message_id = data["message_id"]
    button_id = data["button_id"]

    print(
        "ABOUT TO PROCESS:",
        {
            "type": data.get("type"),
            "text": data.get("text"),
            "button_id": data.get("button_id"),
            "unsupported": data.get("unsupported"),
            "is_status": data.get("is_status"),
        },
    )
    try:
        # 🔒 LOCK conversación
        chat = get_or_create_session(db, phone)

        # 🚫 anti duplicado
        if chat.last_message_id == message_id:
            db.rollback()
            return {"status": "duplicate"}

        start = time.time()

        # 🧠 MOTOR CONVERSACIONAL (única decisión)
        result = process_message(
            session=chat,
            text=text,
            intent=button_id,
            db=db,
        )
        print("PATCH RECIBIDO:", result.inconsistencia_patch)

        end = time.time()
        print("COMMIT TIME:", end - start)

        reply = result.reply
        next_state = result.next_state
        buttons = result.buttons
        previous_state = result.previous_state

        print(f"DEBUG: next_state={next_state}, previous_state={previous_state}, buttons={buttons}")

        # --------------------------------------
        # 🧾 Persistencia de inconsistencias
        # --------------------------------------

        # 1) Si flow_engine mandó patch -> lo aplicamos (abre si no existe)
        if result.inconsistencia_patch:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch=result.inconsistencia_patch,
            )

        # 2) Si caímos en estados "problemáticos" -> también abrimos/registramos evento
        if next_state in [
            ChatState.INCONSISTENCIA,
            ChatState.ACLARACION,
            ChatState.LLAMADA,
        ]:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch={
                    "evento": {
                        "ultimo_estado": chat.state,
                        "causa_estado": next_state.value,
                        "ultimo_mensaje": text,
                    }
                },
            )

        # 3) Si finaliza -> cerramos inconsistencia abierta (si existe)
        if next_state == ChatState.FINALIZADO:
            close_open_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
            )

        # --------------------------------------
        # 💾 persistencia chat_sessions
        # --------------------------------------
        update_session(
            session=chat,
            state=next_state.value,
            last_message=text,
            previous_state=previous_state,
            message_id=message_id,
        )

        db.commit()

    except Exception as e:
        db.rollback()
        raise e

    # 📤 responder fuera del lock (ya con commit hecho)
    if reply:
        asyncio.create_task(send_whatsapp_message(phone, reply, buttons, image_id=result.image_id))

    return {"status": "ok"}
