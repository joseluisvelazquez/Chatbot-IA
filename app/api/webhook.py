from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.meta_webhook import parse_meta_payload
from app.adapters.whatsapp_client import send_whatsapp_message
from app.config.settings import settings
from app.core.flow.flow_engine import process_message
from app.core.states.states import ChatState
from app.db.models import Message
from app.db.session import get_db
from app.services.inconsistencias_service import (
    close_open_inconsistencia,
    open_or_patch_inconsistencia,
)
from app.services.media_service import handle_incoming_media
from app.services.message_service import get_message_by_message_id, save_message
from app.services.reminder_service import upsert_inactivity_reminders
from app.services.session_service import get_or_create_session, update_session
from app.services.verification_panel_service import build_verification_snapshot
from app.websockets.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = settings.META_APP_SECRET
    if not secret:
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    provided = signature_header.split("=", 1)[1]

    return hmac.compare_digest(expected, provided)


def validate_webhook_event(data: dict) -> dict:
    if not data.get("phone"):
        raise ValueError("phone requerido")

    if not data.get("message_id"):
        raise ValueError("message_id requerido")

    event_type = data.get("type")
    is_media = event_type in {"image", "document"}
    has_input = bool(data.get("text") or data.get("button_id") or is_media or data.get("unsupported"))

    if not has_input:
        raise ValueError("payload sin input procesable")

    return {
        **data,
        "is_media": is_media,
        "timestamp": data.get("timestamp") or utcnow_naive(),
    }


def has_newer_incoming_message(db: Session, session_id: int, event_time: datetime) -> bool:
    latest = (
        db.query(Message)
        .filter(
            Message.session_id == session_id,
            Message.direction == "in",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )

    return bool(latest and latest.created_at and event_time < latest.created_at)


def build_message_payload(message: Message) -> dict:
    return {
        "id": message.id,
        "phone": message.phone,
        "content": message.content,
        "direction": message.direction,
        "created_at": message.created_at.isoformat() if message.created_at else "",
        "type": getattr(message, "type", None),
        "media_url": getattr(message, "media_url", None),
        "file_name": getattr(message, "file_name", None),
    }


def build_conversation_payload(chat, message: Message) -> dict:
    return {
        "id": chat.id,
        "phone": chat.phone,
        "name": None,
        "last_message": message.content or "",
        "last_message_at": message.created_at.isoformat() if message.created_at else "",
        "unread_count": chat.unread_count or 0,
        "folio": str(chat.folio) if chat.folio else None,
    }


async def broadcast_new_message(chat, message: Message) -> None:
    await manager.send_to_all({
        "type": "new_message",
        "session_id": chat.id,
        "phone": chat.phone,
        "conversation": build_conversation_payload(chat, message),
        "message": build_message_payload(message),
        "unread_count": chat.unread_count,
    })


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
    raw_body = await request.body()
    if not verify_meta_signature(raw_body, request.headers.get("x-hub-signature-256")):
        logger.warning("webhook_signature_invalid")
        return PlainTextResponse("invalid signature", status_code=403)

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        logger.warning("webhook_invalid_json")
        return PlainTextResponse("invalid json", status_code=400)

    data = parse_meta_payload(payload)
    if not data:
        return {"status": "ignored"}

    if data.get("is_status"):
        return {"status": "whatsapp_status"}

    try:
        event = validate_webhook_event(data)
    except ValueError as exc:
        logger.warning("webhook_validation_failed", extra={"reason": str(exc)})
        return {"status": "ignored_invalid_payload"}

    phone = event["phone"]
    message_id = event["message_id"]
    text = event.get("text") or ""
    button_id = event.get("button_id")
    event_time = event["timestamp"]
    is_media = event["is_media"]
    content = "Archivo recibido" if is_media else (text if text else button_id)

    reply = None
    buttons = []
    image_id = None
    saved_msg = None
    bot_msg = None
    snapshot = None

    try:
        chat = get_or_create_session(db, phone)

        if get_message_by_message_id(db, message_id):
            db.rollback()
            return {"status": "duplicate"}

        if event.get("unsupported"):
            await send_whatsapp_message(
                phone,
                "Por favor responde usando las opciones del menu.",
            )
            return {"status": "unsupported_prompt_sent"}

        out_of_order = has_newer_incoming_message(db, chat.id, event_time)
        media_msg = handle_incoming_media(event, chat) if is_media else None

        saved_msg = save_message(
            db=db,
            session_id=chat.id,
            phone=phone,
            direction="in",
            content="[MEDIA]" if is_media else (text if text else f"[BOTON] {button_id}"),
            message_id=message_id,
            type=media_msg.type if media_msg else "text",
            media_url=media_msg.media_url if media_msg else None,
            file_name=media_msg.file_name if media_msg else None,
            created_at=event_time,
        )
        chat.unread_count = (chat.unread_count or 0) + 1

        if out_of_order:
            db.commit()
            db.refresh(saved_msg)
            logger.info(
                "webhook_out_of_order_saved",
                extra={
                    "message_id": message_id,
                    "phone": phone,
                    "session_id": chat.id,
                    "event_time": event_time.isoformat(),
                },
            )
            return {"status": "out_of_order_saved"}

        result = process_message(
            session=chat,
            text=text,
            intent=button_id,
            db=db,
        )
        reply = result.reply
        buttons = result.buttons
        image_id = result.image_id
        next_state = result.next_state
        previous_state = result.previous_state

        if reply:
            bot_msg = save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="out",
                content=reply,
            )

        if result.inconsistencia_patch:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch=result.inconsistencia_patch,
            )

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

        if next_state == ChatState.FINALIZADO:
            close_open_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
            )

        update_session(
            session=chat,
            state=next_state.value,
            last_message=content,
            previous_state=previous_state,
            message_id=message_id,
            last_message_at=max(event_time, utcnow_naive()),
        )

        upsert_inactivity_reminders(db, chat)
        db.commit()

        db.refresh(chat)
        db.refresh(saved_msg)
        if bot_msg:
            db.refresh(bot_msg)

        snapshot = build_verification_snapshot(db, chat)

    except IntegrityError:
        db.rollback()
        logger.info("webhook_duplicate_integrity", extra={"message_id": message_id, "phone": phone})
        return {"status": "duplicate_ignored"}
    except Exception:
        db.rollback()
        logger.exception("webhook_processing_failed", extra={"message_id": message_id, "phone": phone})
        raise

    await broadcast_new_message(chat, saved_msg)

    if bot_msg:
        await broadcast_new_message(chat, bot_msg)

    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 1,
            "messages_out_delta": 1 if bot_msg else 0,
            "session_id": chat.id,
        },
    })

    if snapshot:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": snapshot,
        })

    if reply:
        asyncio.create_task(
            send_whatsapp_message(
                phone,
                reply,
                buttons,
                image_id=image_id,
            )
        )

    return {"status": "ok"}
