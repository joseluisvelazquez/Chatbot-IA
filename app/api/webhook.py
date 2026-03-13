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
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.core.flow_engine import process_message
from app.services.session_service import get_or_create_session, update_session
from app.services.reminder_service import upsert_inactivity_reminders

from app.adapters.meta_webhook import parse_meta_payload
from app.adapters.whatsapp_client import send_whatsapp_message
from app.services.message_service import save_message

router = APIRouter()


def utcnow_naive() -> datetime:
    # Guardamos "naive UTC" para MySQL DATETIME (sin timezone)
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))
    return PlainTextResponse("Error", status_code=403)


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    data = parse_meta_payload(payload)

    if not data:
        return {"status": "ignored"}

    if data.get("is_status"):
        return {"status": "whatsapp_status"}

    if not data.get("text") and not data.get("button_id"):
        return {"status": "ignored_no_user_input"}

    if data.get("unsupported"):
        await send_whatsapp_message(
            data["phone"],
            "Por favor responde usando las opciones del menú 🙂"
        )
        return {"status": "ok"}

    phone = data["phone"]
    text = data.get("text") or ""
    message_id = data.get("message_id")
    button_id = data.get("button_id")
    content = text if text else button_id
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
        chat = get_or_create_session(db, phone)

        save_message(
            db=db,
            session_id=chat.id,
            phone=phone,
            direction="in",
            content = text if text else f"[BOTON] {button_id}",
            message_id=message_id
        )

        # Anti-duplicado
        if message_id and chat.last_message_id == message_id:
            db.rollback()
            return {"status": "duplicate"}

        result = process_message(
            session=chat,
            text=text,
            intent=button_id,
            db=db,
        )
        reply = result.reply
        next_state = result.next_state
        buttons = result.buttons
        previous_state = result.previous_state

        # Guardar respuesta del bot en la conversación (antes de enviar, para asegurar persistencia aunque falle el envío)
        if reply:
            save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="out",
                content=reply
            )

        now = utcnow_naive()

        print(
            f"DEBUG: next_state={next_state}, previous_state={previous_state}, buttons={buttons}"
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)

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
            last_message=content,
            previous_state=previous_state,
            message_id=message_id,
            last_message_at=now,  # ✅ clave
        )

        # Reprograma reminders en cada actividad real
        upsert_inactivity_reminders(db, chat)

        db.commit()

    except Exception:
        db.rollback()
        raise

    # 📤 responder fuera del lock (ya con commit hecho)
    if reply:
        asyncio.create_task(send_whatsapp_message(phone, reply, buttons, image_id=result.image_id))

    return {"status": "ok"}
