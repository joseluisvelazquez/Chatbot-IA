from __future__ import annotations

import asyncio
import hmac
import logging
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.whatsapp_client import send_whatsapp_message
from app.config.settings import settings
from app.content import messages
from app.core.states.state_renderer import get_missing_render_fields, render_state
from app.core.states.states import ChatState
from app.db.models import ChatSessions
from app.db.session import get_db
from app.services.message_service import save_message
from app.services.message_metadata import (
    build_outgoing_interactive_metadata,
    build_outgoing_media_metadata,
    merge_message_metadata,
)
from app.services.session_context import reset_verification_context_for_folio
from app.services.siga_bridge import (
    SigaBridgeBadRequestError,
    SigaBridgeConfigError,
    SigaBridgeError,
    SigaBridgeRateLimitError,
    SigaBridgeServerError,
    SigaBridgeUnauthorizedError,
    SigaBridgeUnavailableError,
    get_siga_bridge_client,
)
from app.services.siga_bridge_cache import upsert_cached_verification
from app.services.siga_bridge_sale import bridge_verification_found
from app.siga.siga_repository import obtener_venta_por_folio
from app.utils.timezone import mexico_now_naive

router = APIRouter(tags=["External Triggers"])
logger = logging.getLogger(__name__)

_FOLIO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,31}$")
_REUSABLE_TRIGGER_STATES = {
    ChatState.ESPERA.value,
    ChatState.ESPERANDO_REGISTRO.value,
    ChatState.CAMBIAR_FOLIO.value,
    ChatState.CAMBIAR_FOLIO_DEVOLUCION.value,
    ChatState.CAMBIAR_FOLIO_DESCUENTO.value,
    ChatState.SELECCIONAR_FOLIO.value,
}


class NuevaVentaWebhook(BaseModel):
    phone: str
    folio: str
    no_cuenta: str | None = None
    id_movimiento: str | None = None
    id_venta_b: str | int | None = None


def _mask(value: Any, *, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _normalize_phone(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 10:
        return f"521{digits}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"521{digits[-10:]}"
    if len(digits) > 13:
        return f"521{digits[-10:]}"
    return digits


def _normalize_folio(value: Any) -> str | None:
    folio = str(value or "").strip()
    return folio if folio and _FOLIO_RE.match(folio) else None


def _parse_payload(payload: dict[str, Any]) -> NuevaVentaWebhook:
    phone = _normalize_phone(payload.get("phone"))
    folio = _normalize_folio(payload.get("folio"))
    if not phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="phone is required")
    if not folio:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="folio is required or invalid")

    return NuevaVentaWebhook(
        phone=phone,
        folio=folio,
        no_cuenta=str(payload.get("no_cuenta")).strip() if payload.get("no_cuenta") not in (None, "") else None,
        id_movimiento=str(payload.get("id_movimiento")).strip() if payload.get("id_movimiento") not in (None, "") else None,
        id_venta_b=payload.get("id_venta_b"),
    )


def _verify_api_key(x_api_key: str | None) -> None:
    expected = settings.EXTERNAL_TRIGGER_TOKEN
    if not expected:
        logger.error("external_sale_trigger_token_not_configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="external trigger not configured")
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing API key")
    if not hmac.compare_digest(str(x_api_key), str(expected)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid API key")


def _select_session_for_trigger(db: Session, data: NuevaVentaWebhook) -> tuple[ChatSessions, bool]:
    existing_same_folio = (
        db.query(ChatSessions)
        .filter(ChatSessions.phone == data.phone, ChatSessions.folio == data.folio)
        .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
        .first()
    )
    if existing_same_folio:
        return existing_same_folio, False

    latest = (
        db.query(ChatSessions)
        .filter(ChatSessions.phone == data.phone)
        .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
        .first()
    )
    if latest and (not latest.folio or latest.state in _REUSABLE_TRIGGER_STATES):
        return latest, False

    chat = ChatSessions(
        phone=data.phone,
        folio=data.folio,
        state=ChatState.ESPERA.value,
        extra_json={},
        last_customer_message_at=mexico_now_naive(),
    )
    db.add(chat)
    db.flush()
    return chat, True


async def _force_bridge_snapshot(
    session: ChatSessions,
    folio: str,
    *,
    company_id: int = 1,
) -> dict[str, Any] | None:
    if not settings.SIGA_BRIDGE_ENABLED:
        logger.info(
            "external_sale_trigger_bridge_disabled",
            extra={"session_id": session.id, "folio_masked": _mask(folio)},
        )
        return None

    client = get_siga_bridge_client()
    raw = await client.get_verification(folio, company_id)
    snapshot = upsert_cached_verification(
        session,
        folio,
        raw,
        raw=raw,
    )
    return snapshot


def _bridge_http_status(exc: SigaBridgeError) -> int:
    if isinstance(exc, (SigaBridgeUnavailableError, SigaBridgeServerError, SigaBridgeRateLimitError)):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, (SigaBridgeBadRequestError, SigaBridgeUnauthorizedError, SigaBridgeConfigError)):
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_502_BAD_GATEWAY


async def _send_and_broadcast(chat: ChatSessions, bot_msg, reply_text: str, buttons: list[dict], image_id: str | None) -> None:
    from app.api.webhook import broadcast_new_message

    await broadcast_new_message(chat, bot_msg)
    asyncio.create_task(send_whatsapp_message(chat.phone, reply_text, buttons, image_id=image_id))


async def _send_pending_message(db: Session, chat: ChatSessions) -> None:
    bot_msg = save_message(
        db=db,
        session_id=chat.id,
        phone=chat.phone,
        direction="out",
        content=messages.DATOS_VERIFICACION_PREPARANDO,
    )
    db.flush()
    db.refresh(bot_msg)
    await _send_and_broadcast(chat, bot_msg, messages.DATOS_VERIFICACION_PREPARANDO, [], None)


def _outgoing_metadata(reply_text: str, buttons: list[dict], image_id: str | None) -> tuple[str, str | None, dict[str, Any] | None]:
    flow_media_type = "video" if str(image_id or "").lower().endswith(".mp4") else "image" if image_id else None
    media_metadata = build_outgoing_media_metadata(
        source=image_id,
        caption=reply_text,
        media_type=flow_media_type,
    )
    media = media_metadata.get("media") if isinstance(media_metadata, dict) else None
    return (
        str(media.get("type") or "text") if isinstance(media, dict) else "text",
        media.get("url") if isinstance(media, dict) else None,
        merge_message_metadata(
            build_outgoing_interactive_metadata(reply_text, buttons),
            media_metadata,
        ),
    )


@router.post("/api/external/ventas/trigger")
async def trigger_verificacion(
    payload: dict[str, Any] = Body(default_factory=dict),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _verify_api_key(x_api_key)
    data = _parse_payload(payload)
    now = mexico_now_naive()

    logger.info(
        "external_sale_trigger_received",
        extra={
            "phone_last4": _mask(data.phone),
            "folio_masked": _mask(data.folio),
            "has_no_cuenta": bool(data.no_cuenta),
            "has_id_movimiento": bool(data.id_movimiento),
            "has_id_venta_b": bool(data.id_venta_b),
        },
    )

    chat, created = _select_session_for_trigger(db, data)
    previous_folio = str(chat.folio) if chat.folio else None
    if previous_folio != data.folio:
        reset_verification_context_for_folio(chat, data.folio)
        logger.info(
            "external_sale_trigger_session_folio_updated",
            extra={
                "session_id": chat.id,
                "created": created,
                "previous_folio_masked": _mask(previous_folio),
                "folio_masked": _mask(data.folio),
            },
        )
    else:
        chat.folio = data.folio

    chat.last_message_at = now
    chat.updated_at = now
    chat.last_message = f"SIGA trigger folio {_mask(data.folio)}"

    bridge_snapshot = None
    bridge_error: SigaBridgeError | None = None
    try:
        bridge_snapshot = await _force_bridge_snapshot(chat, data.folio, company_id=1)
    except SigaBridgeError as exc:
        bridge_error = exc
        logger.warning(
            "external_sale_trigger_bridge_failed",
            extra={
                "session_id": chat.id,
                "folio_masked": _mask(data.folio),
                "error_type": exc.__class__.__name__,
                "status_code": exc.status_code,
            },
        )

    venta_local = obtener_venta_por_folio(db, data.folio)
    bridge_found = bridge_verification_found(bridge_snapshot)
    has_minimum_data = bridge_found or venta_local is not None

    logger.info(
        "external_sale_trigger_lookup_result",
        extra={
            "session_id": chat.id,
            "created": created,
            "phone_last4": _mask(data.phone),
            "folio_masked": _mask(data.folio),
            "bridge_found": bridge_found,
            "local_found": venta_local is not None,
            "bridge_error": bridge_error.__class__.__name__ if bridge_error else None,
        },
    )

    if not has_minimum_data:
        chat.state = ChatState.ESPERANDO_REGISTRO.value
        chat.previous_state = None
        if not bridge_error:
            await _send_pending_message(db, chat)
        db.commit()
        db.refresh(chat)
        if bridge_error:
            raise HTTPException(
                status_code=_bridge_http_status(bridge_error),
                detail="SIGA Bridge lookup failed",
            )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending",
                "message": "Venta aun no disponible en SIGA Bridge.",
                "session_id": chat.id,
                "folio": data.folio,
            },
        )

    missing_fields = get_missing_render_fields(ChatState.INICIO, chat, db)
    if missing_fields:
        chat.state = ChatState.ESPERANDO_REGISTRO.value
        chat.previous_state = None
        await _send_pending_message(db, chat)
        db.commit()
        db.refresh(chat)
        logger.warning(
            "external_sale_trigger_missing_minimum_fields",
            extra={
                "session_id": chat.id,
                "folio_masked": _mask(data.folio),
                "missing_fields": missing_fields,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending",
                "message": "Venta encontrada con datos incompletos.",
                "session_id": chat.id,
                "folio": data.folio,
                "missing_fields": missing_fields,
            },
        )

    reply_text, botones_inicio, image_id = render_state(ChatState.INICIO, chat, db)
    if not reply_text or "{" in reply_text:
        chat.state = ChatState.ESPERANDO_REGISTRO.value
        chat.previous_state = None
        await _send_pending_message(db, chat)
        db.commit()
        db.refresh(chat)
        logger.error(
            "external_sale_trigger_render_blocked",
            extra={"session_id": chat.id, "folio_masked": _mask(data.folio)},
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending",
                "message": "No se pudo renderizar verificacion con datos completos.",
                "session_id": chat.id,
                "folio": data.folio,
            },
        )

    outgoing_type, outgoing_media_url, extra_json = _outgoing_metadata(
        reply_text,
        botones_inicio,
        image_id,
    )
    bot_msg = save_message(
        db=db,
        session_id=chat.id,
        phone=chat.phone,
        direction="out",
        content=reply_text,
        type=outgoing_type,
        media_url=outgoing_media_url,
        extra_json=extra_json,
    )
    chat.state = ChatState.INICIO.value
    chat.previous_state = None
    chat.last_message = "Inicio de verificacion desde SIGA"
    chat.last_message_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(chat)
    db.refresh(bot_msg)

    logger.info(
        "external_sale_trigger_started_verification",
        extra={
            "session_id": chat.id,
            "created": created,
            "phone_last4": _mask(chat.phone),
            "folio_masked": _mask(data.folio),
            "state": chat.state,
        },
    )

    await _send_and_broadcast(chat, bot_msg, reply_text, botones_inicio, image_id)
    return {
        "status": "success",
        "message": "Sesion actualizada y verificacion iniciada.",
        "session_id": chat.id,
        "folio": data.folio,
    }
