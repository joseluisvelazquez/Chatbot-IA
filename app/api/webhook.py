from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.adapters.meta_webhook import parse_meta_payload
from app.adapters.whatsapp_client import send_whatsapp_message
from app.config.settings import settings
from app.core.flow.flow_engine import (
    ACTIVE_VERIFICATION_STATES,
    SERVICE_STATES_WITH_VERIFICATION_CONTEXT,
    STATES_ALLOW_BARE_FOLIO,
    process_message,
)
from app.core.flow.flow import FLOW
from app.core.states.states import ChatState
from app.core.verification_steps import STEP_ORDER
from app.db.models import ChatSessions, FlowEvent, Inconsistencias, Message
from app.db.session import SessionLocal, get_db
from app.services.inconsistencias_service import (
    close_open_inconsistencia,
    open_or_patch_inconsistencia,
)
from app.services.media_service import handle_incoming_media
from app.services.message_service import get_message_by_message_id, save_message
from app.services.message_metadata import (
    build_outgoing_interactive_metadata,
    build_outgoing_media_metadata,
    merge_message_metadata,
)
from app.services.reminder_service import upsert_inactivity_reminders
from app.services.session_service import get_or_create_session, update_session
from app.services.siga_bridge_integration import (
    ensure_comprobante_access_data,
    lookup_customer_for_incoming_phone,
    lookup_verification_for_folio,
)
from app.services.siga_bridge_sale import (
    bridge_verification_found,
    get_cached_bridge_verification_payload,
)
from app.services.verification_panel_service import build_verification_snapshot
from app.services.verification_tracker import STEP_MAP
from app.services.ws_events import (
    build_conversation_updated_event,
    build_inconsistency_created_event,
    build_inconsistency_updated_event,
    build_message_payload,
    build_new_message_event,
    build_reaction_update_event,
    build_siga_snapshot_updated_event,
    build_verification_context_changed_event,
    build_verification_updated_event,
    minimal_verification_payload,
)
from app.services.message_reaction_service import (
    delete_reaction,
    serialize_reaction,
    upsert_reaction,
)
from app.utils.folio_parser import extraer_folio_si_mensaje_de_folio
from app.utils.timezone import mexico_now_naive
from app.websockets.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)
_WEBHOOK_PHONE_LOCKS: dict[str, asyncio.Lock] = {}
_SIGA_DETAIL_ROLES = {"admin", "jefe_operativo", "sistemas"}


def utcnow_naive() -> datetime:
    return mexico_now_naive()


def _phone_lock(phone: str) -> asyncio.Lock:
    key = str(phone or "")
    lock = _WEBHOOK_PHONE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _WEBHOOK_PHONE_LOCKS[key] = lock
    return lock


def _release_lock(lock: asyncio.Lock | None) -> None:
    if lock and lock.locked():
        lock.release()


def _mask_last(value: Any, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _coerce_chat_state(value: Any) -> ChatState | None:
    if isinstance(value, ChatState):
        return value
    if not value:
        return None
    try:
        return ChatState(value)
    except ValueError:
        return None


def _active_verification_context_state(chat: ChatSessions) -> ChatState | None:
    current_state = _coerce_chat_state(getattr(chat, "state", None))
    if current_state in ACTIVE_VERIFICATION_STATES:
        return current_state

    previous_state = _coerce_chat_state(getattr(chat, "previous_state", None))
    if (
        current_state in SERVICE_STATES_WITH_VERIFICATION_CONTEXT
        and previous_state in ACTIVE_VERIFICATION_STATES
    ):
        return previous_state

    return None


def _incoming_folio_for_bridge_lookup(text: str, chat: ChatSessions) -> str | None:
    current_state = _coerce_chat_state(getattr(chat, "state", None))
    allow_bare = current_state in STATES_ALLOW_BARE_FOLIO
    return extraer_folio_si_mensaje_de_folio(
        text,
        allow_folio_suelto=allow_bare,
    )


def _would_overwrite_active_bridge_context(chat: ChatSessions, folio: str | None) -> bool:
    if not folio or not getattr(chat, "folio", None):
        return False
    if str(folio) == str(chat.folio):
        return False
    return _active_verification_context_state(chat) is not None


def _event_log_meta(event: dict[str, Any]) -> dict[str, Any]:
    reaction = event.get("extra_json", {}).get("reaction") if isinstance(event.get("extra_json"), dict) else {}
    sticker = event.get("extra_json", {}).get("sticker") if isinstance(event.get("extra_json"), dict) else {}
    return {
        "message_id": event.get("message_id"),
        "phone_last4": _mask_last(event.get("phone")),
        "event_type": event.get("type"),
        "incoming_message_type": event.get("type"),
        "has_text": bool(event.get("text")),
        "has_button": bool(event.get("button_id")),
        "is_media": bool(event.get("is_media")),
        "reaction_message_id": reaction.get("message_id") if isinstance(reaction, dict) else None,
        "reaction_emoji": reaction.get("emoji") if isinstance(reaction, dict) else None,
        "sticker_mime_type": sticker.get("mime_type") if isinstance(sticker, dict) else event.get("mime_type"),
    }


def _button_label_for_panel(button_id: str | None, chat: ChatSessions | None) -> str | None:
    if not button_id:
        return None

    candidate_states = [
        getattr(chat, "state", None),
        getattr(chat, "previous_state", None),
        ChatState.MENU_AYUDA.value,
        ChatState.FINALIZADO.value,
    ]
    for state_value in candidate_states:
        state = _coerce_chat_state(state_value)
        if not state:
            continue
        for button in FLOW.get(state, {}).get("buttons", []):
            if button.get("id") == button_id:
                label = str(button.get("label") or "").strip()
                return f"Cliente selecciono: {label}" if label else None

    if button_id.startswith("SELECCIONAR_FOLIO_"):
        return f"Cliente selecciono: Seleccionar folio {button_id.replace('SELECCIONAR_FOLIO_', '')}"

    return f"Cliente selecciono: {button_id.replace('_', ' ').title()}"


def _event_content_for_panel(event: dict[str, Any], chat: ChatSessions | None = None) -> str:
    if event.get("button_id"):
        metadata = event.get("extra_json") if isinstance(event.get("extra_json"), dict) else {}
        reply = metadata.get("interactive_reply") if isinstance(metadata.get("interactive_reply"), dict) else {}
        title = str(reply.get("title") or event.get("text") or "").strip()
        if title:
            return f"Cliente selecciono: {title}"
        return _button_label_for_panel(event.get("button_id"), chat) or "[BOTON]"
    text = event.get("text")

    event_type = str(event.get("type") or "unknown").lower()
    labels = {
        "image": "[IMAGEN] Imagen recibida",
        "document": "[DOCUMENTO] Documento recibido",
        "video": "[VIDEO] Video recibido",
        "sticker": "🧩 Sticker recibido",
        "audio": "[AUDIO] Audio recibido",
        "reaction": "Reaccion recibida",
    }
    if event_type in labels:
        return f"{labels[event_type]}: {text}" if text else labels[event_type]
    if text:
        return text
    return f"[ARCHIVO] Mensaje {event_type} recibido"


def _outgoing_media_fields(image_id: str | None, reply: str | None) -> tuple[str, str | None, dict[str, Any] | None]:
    flow_media_type = "video" if str(image_id or "").lower().endswith(".mp4") else "image" if image_id else None
    media_metadata = build_outgoing_media_metadata(
        source=image_id,
        caption=reply,
        media_type=flow_media_type,
    )
    media = media_metadata.get("media") if isinstance(media_metadata, dict) else None
    if not isinstance(media, dict):
        return "text", None, None
    return str(media.get("type") or "text"), media.get("url"), media_metadata


async def emit_ws_message(message: dict[str, Any], *, roles: set[str] | None = None) -> None:
    payload = message.get("payload")
    session_id = message.get("session_id")
    if session_id is None and isinstance(payload, dict):
        session_id = payload.get("session_id")
    await manager.send_to_all(message, roles=roles)
    logger.info(
        "webhook_ws_event_emitted",
        extra={
            "event_type": message.get("type"),
            "session_id": session_id,
            "roles": sorted(roles) if roles else None,
        },
    )


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
    is_media = event_type in {"image", "document", "sticker"}
    is_reaction = event_type == "reaction"
    has_input = bool(data.get("text") or data.get("button_id") or is_media or is_reaction or data.get("unsupported"))

    if not has_input:
        raise ValueError("payload sin input procesable")

    return {
        **data,
        "is_media": is_media,
        "is_reaction": is_reaction,
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


async def broadcast_new_message(chat, message: Message) -> None:
    await emit_ws_message(build_new_message_event(chat, message))


async def _send_whatsapp_and_update_message_id(
    *,
    db_message_id: int | None,
    phone: str,
    text: str | None,
    buttons: list | None = None,
    image_id: str | None = None,
) -> None:
    response = await send_whatsapp_message(phone, text, buttons, image_id=image_id)
    if not db_message_id or response is None:
        return
    try:
        body = response.json()
    except Exception:
        return
    messages = body.get("messages") if isinstance(body, dict) else None
    provider_message_id = None
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        provider_message_id = messages[0].get("id")
    if not provider_message_id:
        return

    db = SessionLocal()
    try:
        message = db.query(Message).filter(Message.id == db_message_id).first()
        if message and not message.message_id:
            message.message_id = str(provider_message_id)
            db.commit()
            logger.info(
                "outgoing_message_provider_id_persisted",
                extra={"message_db_id": db_message_id, "provider_message_id": provider_message_id},
            )
    except Exception:
        db.rollback()
        logger.warning("outgoing_message_provider_id_persist_failed", extra={"message_db_id": db_message_id})
    finally:
        db.close()


def open_inconsistency_ids(db: Session, session_id: int | None) -> set[int]:
    if not session_id:
        return set()
    rows = (
        db.query(Inconsistencias.id)
        .filter(
            Inconsistencias.session_id == session_id,
            func.upper(Inconsistencias.estatus) == "ABIERTA",
        )
        .all()
    )
    return {int(row.id) for row in rows if row.id is not None}


def load_inconsistencies_by_ids(db: Session, ids: set[int]) -> list[Inconsistencias]:
    if not ids:
        return []
    return (
        db.query(Inconsistencias)
        .filter(Inconsistencias.id.in_(ids))
        .order_by(Inconsistencias.id.asc())
        .all()
    )


def _reaction_info(event: dict[str, Any]) -> dict[str, Any]:
    extra = event.get("extra_json") if isinstance(event.get("extra_json"), dict) else {}
    reaction = extra.get("reaction") if isinstance(extra.get("reaction"), dict) else {}
    return {
        "wa_message_id_original": reaction.get("message_id"),
        "emoji": reaction.get("emoji"),
    }


async def persist_and_emit_reaction_event(
    *,
    db: Session,
    chat: ChatSessions,
    event: dict[str, Any],
    total_sessions_delta: int,
    active_sessions_delta: int,
) -> None:
    info = _reaction_info(event)
    target_wa_id = info.get("wa_message_id_original")
    emoji = info.get("emoji")
    phone = event["phone"]
    event_time = event["timestamp"]

    target_msg = get_message_by_message_id(db, target_wa_id)
    if target_msg:
        if emoji:
            reaction = upsert_reaction(
                db,
                target_message=target_msg,
                wa_message_id_original=target_wa_id,
                reacted_by_phone=phone,
                reaction_emoji=emoji,
                reacted_at=event_time,
            )
            db.flush()
            payload_reaction = serialize_reaction(reaction)
            removed = False
            action = getattr(reaction, "_reaction_action", "update")
        else:
            removed_row = delete_reaction(
                db,
                wa_message_id_original=target_wa_id,
                reacted_by_phone=phone,
            )
            payload_reaction = {
                "wa_message_id_original": target_wa_id,
                "reacted_by_phone": phone,
            }
            removed = True
            action = "delete"

        db.commit()
        await emit_ws_message(
            build_reaction_update_event(
                session_id=target_msg.session_id,
                message_id=target_msg.id,
                wa_message_id_original=target_wa_id,
                reaction=payload_reaction,
                removed=removed,
                action=action,
            )
        )
        logger.info(
            "webhook_reaction_persisted",
            extra={
                **_event_log_meta(event),
                "session_id": target_msg.session_id,
                "target_message_db_id": target_msg.id,
                "removed": removed,
                "reaction_action": action,
            },
        )
        return

    if not emoji:
        db.commit()
        logger.info("webhook_reaction_delete_without_target_ignored", extra=_event_log_meta(event))
        return

    content = f"El cliente reacciono con {emoji} a un mensaje anterior"
    saved_msg = save_message(
        db=db,
        session_id=chat.id,
        phone=phone,
        direction="in",
        content=content,
        message_id=event["message_id"],
        type="reaction",
        created_at=event_time,
        extra_json=event.get("extra_json"),
    )
    chat.unread_count = (chat.unread_count or 0) + 1
    update_session(
        session=chat,
        state=chat.state,
        last_message=content,
        previous_state=chat.previous_state,
        message_id=event["message_id"],
        last_message_at=max(event_time, utcnow_naive()),
        last_customer_message_at=max(event_time, utcnow_naive()),
    )
    db.flush()
    db.commit()
    db.refresh(chat)
    db.refresh(saved_msg)

    await broadcast_new_message(chat, saved_msg)
    await emit_ws_message(build_conversation_updated_event(chat, source="reaction"))
    await emit_ws_message({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 1,
            "messages_out_delta": 0,
            "total_sessions_delta": total_sessions_delta,
            "active_sessions_delta": active_sessions_delta,
            "issues_open_delta": 0,
            "funnel_steps_delta": [],
            "session_id": chat.id,
        },
    })
    await emit_ws_message(
        build_reaction_update_event(
            session_id=chat.id,
            wa_message_id_original=target_wa_id,
            reaction={
                "wa_message_id_original": target_wa_id,
                "reaction_emoji": emoji,
                "reacted_by_phone": phone,
            },
            action="add",
            orphan=True,
            event_message=build_message_payload(saved_msg),
        )
    )


def count_open_issues(db: Session) -> int:
    return (
        db.query(func.count(Inconsistencias.id))
        .filter(func.lower(Inconsistencias.estatus) == "abierta")
        .scalar()
        or 0
    )


def get_reached_funnel_steps(
    db: Session,
    session_id: int,
    date_from: datetime,
    folio: str | None = None,
) -> set[str]:
    expected_folio = str(folio) if folio else None
    rows = (
        db.query(FlowEvent.to_state, FlowEvent.folio)
        .filter(
            FlowEvent.session_id == session_id,
            FlowEvent.to_state.isnot(None),
            FlowEvent.created_at >= date_from,
        )
        .all()
    )

    return {
        step
        for to_state, event_folio in rows
        if (
            not expected_folio
            or event_folio is None
            or str(event_folio) == expected_folio
        )
        if (step := STEP_MAP.get(to_state))
    }


def build_funnel_step_deltas(
    next_state: ChatState | str | None,
    existing_steps: set[str],
) -> list[dict]:
    next_step = STEP_MAP.get(next_state)
    if next_step not in STEP_ORDER:
        return []

    max_index = STEP_ORDER.index(next_step)
    return [
        {"step": step, "delta": 1}
        for step in STEP_ORDER[:max_index + 1]
        if step not in existing_steps
    ]


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
    try:
        raw_body = await request.body()
    except ClientDisconnect:
        logger.info("webhook_client_disconnected_before_body")
        return {"status": "client_disconnected"}

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
    content = _event_content_for_panel(event)

    reply = None
    buttons = []
    image_id = None
    saved_msg = None
    bot_msg = None
    snapshot = None
    existing_funnel_steps = set()
    funnel_step_deltas = []
    total_sessions_delta = 0
    active_sessions_delta = 0
    issues_open_delta = 0
    open_inconsistency_ids_before: set[int] = set()
    created_inconsistency_ids: set[int] = set()
    closed_inconsistency_ids: set[int] = set()
    bridge_verification = None
    previous_folio = None
    verification_context_changed = False
    processing_started_at = time.perf_counter()
    lock = _phone_lock(phone)
    lock_acquired = False

    logger.info("webhook_received", extra=_event_log_meta(event))
    if lock.locked():
        logger.info(
            "webhook_session_lock_wait",
            extra={"message_id": message_id, "phone_last4": _mask_last(phone)},
        )
    await lock.acquire()
    lock_acquired = True

    try:
        logger.info("webhook_processing_started", extra=_event_log_meta(event))
        existing_session = (
            db.query(ChatSessions.id, ChatSessions.last_message_at)
            .filter(ChatSessions.phone == phone)
            .first()
        )
        total_sessions_delta = 0 if existing_session else 1
        was_active = bool(
            existing_session
            and existing_session.last_message_at
            and existing_session.last_message_at >= utcnow_naive() - timedelta(days=1)
        )
        active_sessions_delta = 0 if was_active else 1
        open_issues_before = count_open_issues(db)

        chat = get_or_create_session(
            db,
            phone,
            text=text,
            intent=button_id or "",
        )
        content = _event_content_for_panel(event, chat)
        previous_folio = str(chat.folio) if chat.folio else None
        incoming_folio = _incoming_folio_for_bridge_lookup(text, chat)
        open_inconsistency_ids_before = open_inconsistency_ids(db, chat.id)

        if get_message_by_message_id(db, message_id):
            db.rollback()
            logger.info(
                "webhook_duplicate_ignored",
                extra={
                    **_event_log_meta(event),
                    "duration_ms": round((time.perf_counter() - processing_started_at) * 1000, 2),
                },
            )
            _release_lock(lock)
            lock_acquired = False
            return {"status": "duplicate"}

        if event.get("is_reaction"):
            await persist_and_emit_reaction_event(
                db=db,
                chat=chat,
                event=event,
                total_sessions_delta=total_sessions_delta,
                active_sessions_delta=active_sessions_delta,
            )
            _release_lock(lock)
            lock_acquired = False
            logger.info("webhook_processing_finished", extra={**_event_log_meta(event), "session_id": chat.id, "status": "reaction"})
            return {"status": "reaction"}

        if event.get("type") == "sticker":
            media_msg = handle_incoming_media(event, chat)
            saved_msg = save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="in",
                content="🧩 Sticker recibido",
                message_id=message_id,
                type="sticker",
                media_url=media_msg.media_url if media_msg else None,
                created_at=event_time,
                extra_json=event.get("extra_json"),
            )
            chat.unread_count = (chat.unread_count or 0) + 1
            update_session(
                session=chat,
                state=chat.state,
                last_message="🧩 Sticker recibido",
                previous_state=chat.previous_state,
                message_id=message_id,
                last_message_at=max(event_time, utcnow_naive()),
                last_customer_message_at=max(event_time, utcnow_naive()),
            )
            db.flush()
            db.commit()
            db.refresh(chat)
            db.refresh(saved_msg)
            _release_lock(lock)
            lock_acquired = False
            await broadcast_new_message(chat, saved_msg)
            await emit_ws_message(build_conversation_updated_event(chat, source="sticker"))
            await emit_ws_message({
                "type": "dashboard_update",
                "payload": {
                    "messages_in_delta": 1,
                    "messages_out_delta": 0,
                    "total_sessions_delta": total_sessions_delta,
                    "active_sessions_delta": active_sessions_delta,
                    "issues_open_delta": 0,
                    "funnel_steps_delta": [],
                    "session_id": chat.id,
                },
            })
            logger.info("webhook_processing_finished", extra={**_event_log_meta(event), "session_id": chat.id, "status": "sticker"})
            return {"status": "sticker"}

        if event.get("unsupported"):
            unsupported_content = _event_content_for_panel(event, chat)
            saved_msg = save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="in",
                content=unsupported_content,
                message_id=message_id,
                type=str(event.get("type") or "unsupported"),
                created_at=event_time,
                extra_json=event.get("extra_json"),
            )
            chat.unread_count = (chat.unread_count or 0) + 1
            reply = "Por favor responde usando las opciones del menu."
            bot_msg = save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="out",
                content=reply,
            )
            update_session(
                session=chat,
                state=chat.state,
                last_message=unsupported_content,
                previous_state=chat.previous_state,
                message_id=message_id,
                last_message_at=max(event_time, utcnow_naive()),
                last_customer_message_at=max(event_time, utcnow_naive()),
            )
            db.flush()
            db.commit()
            db.refresh(chat)
            db.refresh(saved_msg)
            db.refresh(bot_msg)
            logger.info("webhook_message_persisted", extra={**_event_log_meta(event), "session_id": chat.id})
            _release_lock(lock)
            lock_acquired = False
            await broadcast_new_message(chat, saved_msg)
            await broadcast_new_message(chat, bot_msg)
            await emit_ws_message(build_conversation_updated_event(chat, source="webhook"))
            await emit_ws_message({
                "type": "dashboard_update",
                "payload": {
                    "messages_in_delta": 1,
                    "messages_out_delta": 1,
                    "total_sessions_delta": total_sessions_delta,
                    "active_sessions_delta": active_sessions_delta,
                    "issues_open_delta": 0,
                    "funnel_steps_delta": [],
                    "session_id": chat.id,
                },
            })
            logger.info(
                "webhook_processing_finished",
                extra={
                    **_event_log_meta(event),
                    "session_id": chat.id,
                    "status": "unsupported_prompt_sent",
                    "duration_ms": round((time.perf_counter() - processing_started_at) * 1000, 2),
                },
            )
            asyncio.create_task(
                _send_whatsapp_and_update_message_id(
                    db_message_id=bot_msg.id if bot_msg else None,
                    phone=phone,
                    text=reply,
                )
            )
            return {"status": "unsupported_prompt_sent"}

        out_of_order = has_newer_incoming_message(db, chat.id, event_time)
        existing_funnel_steps = get_reached_funnel_steps(
            db,
            chat.id,
            utcnow_naive() - timedelta(days=7),
            folio=str(incoming_folio or chat.folio or "") or None,
        )
        media_msg = handle_incoming_media(event, chat) if is_media else None

        saved_msg = save_message(
            db=db,
            session_id=chat.id,
            phone=phone,
            direction="in",
                content=content,
            message_id=message_id,
            type=media_msg.type if media_msg else "text",
            media_url=media_msg.media_url if media_msg else None,
            file_name=media_msg.file_name if media_msg else None,
            created_at=event_time,
            extra_json=event.get("extra_json"),
        )
        chat.unread_count = (chat.unread_count or 0) + 1
        db.flush()
        logger.info("webhook_message_persisted", extra={**_event_log_meta(event), "session_id": chat.id})

        if out_of_order:
            db.commit()
            db.refresh(chat)
            db.refresh(saved_msg)
            logger.info(
                "webhook_out_of_order_saved",
                extra={
                    "message_id": message_id,
                    "phone_last4": _mask_last(phone),
                    "session_id": chat.id,
                    "event_time": event_time.isoformat(),
                },
            )
            _release_lock(lock)
            lock_acquired = False
            await broadcast_new_message(chat, saved_msg)
            await emit_ws_message(build_conversation_updated_event(chat, source="webhook"))
            await emit_ws_message({
                "type": "dashboard_update",
                "payload": {
                    "messages_in_delta": 1,
                    "messages_out_delta": 0,
                    "total_sessions_delta": total_sessions_delta,
                    "active_sessions_delta": active_sessions_delta,
                    "issues_open_delta": 0,
                    "funnel_steps_delta": [],
                    "session_id": chat.id,
                },
            })
            logger.info(
                "webhook_processing_finished",
                extra={
                    **_event_log_meta(event),
                    "session_id": chat.id,
                    "status": "out_of_order_saved",
                    "duration_ms": round((time.perf_counter() - processing_started_at) * 1000, 2),
                },
            )
            return {"status": "out_of_order_saved"}

        # 🔔 INTERCEPCIÓN: Activación de notificaciones para asesores
        if text.strip().lower() == "activar notificaciones":
            reply = "✅ *Notificaciones activadas*\nTu ventana de 24h está abierta para recibir alertas."
            
            # El mensaje entrante ya fue persistido antes de este caso especial.
            bot_msg = save_message(db, chat.id, phone, "out", reply)
            
            # Actualizar la sesión para abrir la ventana de Meta
            update_session(
                session=chat,
                state=chat.state, # mantener el estado actual
                last_message=text,
                previous_state=chat.previous_state,
                message_id=message_id,
                last_message_at=max(event_time, utcnow_naive()),
                last_customer_message_at=max(event_time, utcnow_naive()) # 🔑 Clave para Meta
            )
            db.commit()
            db.refresh(chat)
            db.refresh(saved_msg)
            db.refresh(bot_msg)

            _release_lock(lock)
            lock_acquired = False
            await broadcast_new_message(chat, saved_msg)
            await broadcast_new_message(chat, bot_msg)
            await emit_ws_message(build_conversation_updated_event(chat, source="webhook"))
            await emit_ws_message({
                "type": "dashboard_update",
                "payload": {
                    "messages_in_delta": 1,
                    "messages_out_delta": 1,
                    "total_sessions_delta": total_sessions_delta,
                    "active_sessions_delta": active_sessions_delta,
                    "issues_open_delta": 0,
                    "funnel_steps_delta": [],
                    "session_id": chat.id,
                },
            })
            asyncio.create_task(
                _send_whatsapp_and_update_message_id(
                    db_message_id=bot_msg.id if bot_msg else None,
                    phone=phone,
                    text=reply,
                )
            )
            return {"status": "advisor_activated"}

        lookup_skipped_for_active_context = False
        if settings.SIGA_BRIDGE_ENABLED and incoming_folio:
            if _would_overwrite_active_bridge_context(chat, incoming_folio):
                lookup_skipped_for_active_context = True
                logger.info(
                    "siga_bridge_lookup_skipped_active_context",
                    extra={
                        "session_id": chat.id,
                        "current_folio_masked": _mask_last(chat.folio),
                        "incoming_folio_masked": _mask_last(incoming_folio),
                        "message_id": message_id,
                    },
                )
            else:
                bridge_verification = await lookup_verification_for_folio(
                    incoming_folio,
                    company_id=1,
                    session=chat,
                    force_refresh=True,
                    allow_stale_on_error=False,
                )
                if bridge_verification:
                    logger.info(
                        "siga_snapshot_updated_from_webhook",
                        extra={
                            "session_id": chat.id,
                            "folio_masked": _mask_last(incoming_folio),
                            "message_id": message_id,
                        },
                    )

        cached_bridge_payload = (
            get_cached_bridge_verification_payload(chat, str(chat.folio))
            if chat.folio
            else None
        )
        if (
            settings.SIGA_BRIDGE_ENABLED
            and chat.folio
            and (not incoming_folio or lookup_skipped_for_active_context)
            and not bridge_verification_found(cached_bridge_payload)
        ):
            bridge_verification = await lookup_verification_for_folio(
                str(chat.folio),
                company_id=1,
                session=chat,
                force_refresh=True,
                allow_stale_on_error=False,
            ) or bridge_verification

        if (
            settings.SIGA_BRIDGE_ENABLED
            and chat.folio
            and chat.state in {
                ChatState.INFO_METODOS_PAGO.value,
                ChatState.INFO_COMPROBANTE_ACCESO.value,
            }
        ):
            bridge_verification = await ensure_comprobante_access_data(
                chat,
                str(chat.folio),
                company_id=1,
                bridge_verification=bridge_verification,
            ) or bridge_verification

        result = process_message(
            session=chat,
            text=text,
            intent=button_id,
            db=db,
            bridge_verification=bridge_verification,
        )
        reply = result.reply
        buttons = result.buttons
        image_id = result.image_id
        next_state = result.next_state
        previous_state = result.previous_state
        funnel_step_deltas = build_funnel_step_deltas(
            next_state,
            existing_funnel_steps,
        )

        if reply:
            outgoing_type, outgoing_media_url, media_metadata = _outgoing_media_fields(image_id, reply)
            outgoing_metadata = merge_message_metadata(
                build_outgoing_interactive_metadata(reply, buttons),
                media_metadata,
            )
            bot_msg = save_message(
                db=db,
                session_id=chat.id,
                phone=phone,
                direction="out",
                content=reply,
                type=outgoing_type,
                media_url=outgoing_media_url,
                extra_json=outgoing_metadata,
            )

        if result.inconsistencia_patch:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch=result.inconsistencia_patch,
            )


        if next_state == ChatState.FINALIZADO:
            close_open_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
            )

        old_state = chat.state  # capturar antes de actualizar

        update_session(
            session=chat,
            state=next_state.value,
            last_message=content,
            previous_state=previous_state,
            message_id=message_id,
            last_message_at=max(event_time, utcnow_naive()),
            last_customer_message_at=max(event_time, utcnow_naive()),
        )

        upsert_inactivity_reminders(db, chat)
        db.commit()
        issues_open_delta = count_open_issues(db) - open_issues_before
        open_inconsistency_ids_after = open_inconsistency_ids(db, chat.id)
        created_inconsistency_ids = open_inconsistency_ids_after - open_inconsistency_ids_before
        closed_inconsistency_ids = open_inconsistency_ids_before - open_inconsistency_ids_after

        # 🔔 Notificar a asesores si el nuevo estado requiere atención
        from app.services.notification_service import notify_if_attention_needed
        no_cuenta_val = bridge_verification.get("no_cuenta") if isinstance(bridge_verification, dict) else None
        
        # Si no lo tenemos del bridge, intentar resolverlo de la DB local
        if not no_cuenta_val and chat.folio:
            try:
                from app.services.verification_panel_service import resolve_no_cuenta
                no_cuenta_val = resolve_no_cuenta(db, str(chat.folio))
            except Exception:
                pass

        asyncio.create_task(
            notify_if_attention_needed(chat, old_state, next_state.value, no_cuenta=no_cuenta_val)
        )

        db.refresh(chat)
        db.refresh(saved_msg)
        if bot_msg:
            db.refresh(bot_msg)

        snapshot = build_verification_snapshot(db, chat)
        current_folio = str(chat.folio) if chat.folio else None
        verification_context_changed = previous_folio != current_folio

        if settings.SIGA_BRIDGE_ENABLED:
            asyncio.create_task(
                lookup_customer_for_incoming_phone(
                    phone,
                    company_id=1,
                    session_id=chat.id,
                )
            )

    except IntegrityError:
        db.rollback()
        _release_lock(lock)
        lock_acquired = False
        logger.info("webhook_duplicate_ignored", extra={**_event_log_meta(event), "reason": "integrity"})
        return {"status": "duplicate_ignored"}
    except Exception:
        db.rollback()
        _release_lock(lock)
        lock_acquired = False
        logger.exception(
            "webhook_processing_failed",
            extra={
                **_event_log_meta(event),
                "duration_ms": round((time.perf_counter() - processing_started_at) * 1000, 2),
            },
        )
        return {"status": "processing_failed"}

    if lock_acquired:
        _release_lock(lock)
        lock_acquired = False

    await broadcast_new_message(chat, saved_msg)

    if bot_msg:
        await broadcast_new_message(chat, bot_msg)

    for inc in load_inconsistencies_by_ids(db, created_inconsistency_ids):
        await emit_ws_message(build_inconsistency_created_event(inc))

    for inc in load_inconsistencies_by_ids(db, closed_inconsistency_ids):
        await emit_ws_message(build_inconsistency_updated_event(inc, source="webhook"))

    await emit_ws_message({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 1,
            "messages_out_delta": 1 if bot_msg else 0,
            "total_sessions_delta": total_sessions_delta,
            "active_sessions_delta": active_sessions_delta,
            "issues_open_delta": issues_open_delta,
            "funnel_steps_delta": funnel_step_deltas,
            "session_id": chat.id,
            "folio": chat.folio,
            "reason": "verification_context_changed" if verification_context_changed else "verification_progress",
            "force_refetch_funnel": True,
            "at": utcnow_naive().isoformat(),
        },
    })

    if verification_context_changed:
        context_event = build_verification_context_changed_event(
            chat,
            snapshot,
            previous_folio=previous_folio,
            source="webhook",
        )
        if context_event:
            await emit_ws_message(context_event)

    await emit_ws_message(
        build_conversation_updated_event(
            chat,
            patch={
                "status": next_state.value if isinstance(next_state, ChatState) else str(next_state),
            },
            source="webhook",
        )
    )

    if snapshot:
        minimal_snapshot = minimal_verification_payload(snapshot)
        await emit_ws_message({
            "type": "verification_update",
            "payload": minimal_snapshot,
        })
        verification_event = build_verification_updated_event(snapshot, source="webhook")
        if verification_event:
            await emit_ws_message(verification_event)
        if snapshot.get("siga"):
            siga_event = build_siga_snapshot_updated_event(snapshot, source="webhook")
            if siga_event:
                await emit_ws_message(siga_event, roles=_SIGA_DETAIL_ROLES)

    if reply:
        asyncio.create_task(
            _send_whatsapp_and_update_message_id(
                db_message_id=bot_msg.id if bot_msg else None,
                phone=phone,
                text=reply,
                buttons=buttons,
                image_id=image_id,
            )
        )

    logger.info(
        "webhook_processing_finished",
        extra={
            **_event_log_meta(event),
            "session_id": chat.id,
            "status": "ok",
            "duration_ms": round((time.perf_counter() - processing_started_at) * 1000, 2),
        },
    )
    return {"status": "ok"}
