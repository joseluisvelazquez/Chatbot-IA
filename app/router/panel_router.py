from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.whatsapp_client import send_whatsapp_media, send_whatsapp_message
from app.config.settings import settings
from app.core.verification_steps import STEP_ORDER
from app.db.models import (
    BitacoraVentas,
    ChatSessions,
    FlowEvent,
    Inconsistencias,
    Message,
    PanelFeatureFlag,
    VerificacionCuenta,
)
from app.db.session import get_db
from app.schemas.panel import (
    AssignManagerRequest,
    AvailableManagerResponse,
    BulkReassignRequest,
    CloseSupportTicketRequest,
    ConversationResponse,
    FeatureFlagUpdateRequest,
    MessageResponse,
    OperationReasonRequest,
    PaginatedMessagesResponse,
    SendMessageRequest,
    TakeChatRequest,
    TransferChatRequest,
)
from app.security.auth_dependencies import (
    enforce_panel_origin,
    enforce_panel_ws_origin,
    get_current_panel_user,
    panel_session_cookie_name,
)
from app.security.auth_service import decode_panel_session
from app.security.rbac import (
    apply_chat_visibility_filter,
    build_chat_permission_flags,
    can_view_chat,
    ensure_can_reply_chat,
    ensure_can_view_chat,
    normalize_role,
    require_permission,
)
from app.services.chat_operations import (
    assign_chat_to_manager,
    close_support_ticket,
    devolver_a_gestor,
    devolver_a_soporte,
    initialize_operational_defaults,
    liberar_chat,
    reasignacion_masiva,
    reassign_inactive_manager_chats,
    send_to_assistant,
    technical_ticket_metrics,
    tomar_chat,
    transferir_chat,
)
from app.services.inconsistencias_service import mark_panel_resolution
from app.services.panel_notifications import (
    conversation_operational_payload,
    publish_chat_operation,
)
from app.services.panel_staff import get_available_managers
from app.services.siga_bridge_integration import enrich_verification_with_bridge
from app.services.verification_panel_service import (
    build_verification_snapshot,
    classify_panel_status,
    compute_verification,
    group_inconsistencias_by_folio,
    has_open_inconsistencia,
    resolve_panel_current_step,
)
from app.services.verification_service import VerificationService
from app.services.verification_tracker import STEP_MAP
from app.utils.inconsistencias_serializer import serialize_inconsistencias, summarize_inconsistencias
from app.websockets.manager import manager

router = APIRouter(prefix="/api/panel", tags=["panel"])
logger = logging.getLogger(__name__)

FUNNEL_STEPS = STEP_ORDER
FEATURE_FLAG_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
HTTP_ORIGIN_DEPENDENCIES = [Depends(enforce_panel_origin)]
MAX_CONVERSATIONS_LIMIT = 500
DEFAULT_CONVERSATIONS_LIMIT = 100
MAX_MESSAGES_LIMIT = 250


def rollback_safely(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        logger.exception("panel_rollback_failed")


def require_empresa_panel(user=Depends(get_current_panel_user)):
    allowed_empresa_id = int(getattr(settings, "PANEL_ALLOWED_EMPRESA_ID", 1) or 1)
    if int(user.empresa_id or 0) != allowed_empresa_id:
        logger.warning(
            "panel_empresa_denied",
            extra={
                "username": getattr(user, "username", None),
                "role": getattr(user, "role", None),
                "empresa_id": getattr(user, "empresa_id", None),
                "allowed_empresa_id": allowed_empresa_id,
            },
        )
        raise HTTPException(403, "Empresa no autorizada para panel")
    return user


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    value = str(phone).replace("+", "").strip()
    if value.startswith("52") and len(value) > 10:
        value = value[2:]
    return value[-10:]


def build_siga_url(no_cuenta: str | None, folio: str | None) -> str | None:
    if no_cuenta:
        return f"https://siga.mxcomp.com.mx/cuentas/{no_cuenta}"
    if folio:
        return f"https://siga.mxcomp.com.mx/ventas/{folio}"
    return None


def resolve_cuentas_from_folios(folios: list[str], db: Session, user) -> dict[str, str | None]:
    unique_folios = [str(folio) for folio in dict.fromkeys(folios) if folio]
    result: dict[str, str | None] = {folio: None for folio in unique_folios}

    if not unique_folios:
        return result

    ventas = (
        db.query(BitacoraVentas.folio, BitacoraVentas.no_cuenta)
        .filter(
            BitacoraVentas.folio.in_(unique_folios),
            BitacoraVentas.id_emp_bv == user.empresa_id,
        )
        .order_by(desc(BitacoraVentas.id_venta_b))
        .all()
    )

    for venta in ventas:
        folio = str(venta.folio) if venta.folio else None
        if not folio or folio not in result or result[folio] is not None:
            continue

        if getattr(venta, "no_cuenta", None):
            result[folio] = str(venta.no_cuenta)

    return result


def resolve_names_by_phone(
    db: Session,
    sessions: list[ChatSessions],
    *,
    empresa_id: int,
) -> dict[str, str]:
    normalized_phones = list({
        normalize_phone(session.phone)
        for session in sessions
        if session.phone
    })

    if not normalized_phones:
        return {}

    ventas = (
        db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == empresa_id,
        )
        .all()
    )

    phone_to_name: dict[str, str] = {}
    for venta in ventas:
        if not venta.tel_1 or not venta.nombre_completo:
            continue
        db_phone = normalize_phone(venta.tel_1)
        if db_phone:
            phone_to_name[db_phone] = venta.nombre_completo.strip()

    return phone_to_name


def build_conversation_response(
    session: ChatSessions,
    *,
    user,
    name: str | None = None,
    no_cuenta: str | None = None,
) -> ConversationResponse:
    initialize_operational_defaults(session)
    permissions = build_chat_permission_flags(session, user)

    return ConversationResponse(
        id=session.id,
        phone=session.phone,
        name=name,
        last_message=session.last_message,
        last_message_at=session.last_message_at,
        unread_count=session.unread_count or 0,
        no_cuenta=no_cuenta,
        folio=str(session.folio) if session.folio else None,
        owner_type=session.owner_type,
        assigned_user_id=session.assigned_user_id,
        assigned_role=session.assigned_role,
        status_operativo=session.status_operativo,
        priority=session.priority,
        transfer_pending=bool(session.transfer_pending),
        locked_until=session.locked_until,
        assigned_at=session.assigned_at,
        last_agent_message_at=session.last_agent_message_at,
        last_customer_message_at=session.last_customer_message_at,
        returned_from_role=session.returned_from_role,
        transferred_by_user_id=session.transferred_by_user_id,
        previous_owner_user_id=session.previous_owner_user_id,
        previous_owner_role=session.previous_owner_role,
        transfer_reason=session.transfer_reason,
        transfer_created_at=session.transfer_created_at,
        test_mode=bool(session.test_mode),
        requires_human=bool(session.transfer_pending) or session.status_operativo in {"unassigned", "escalated"},
        **permissions,
    )


async def publish_conversation_refresh(chat: ChatSessions) -> None:
    await manager.send_to_chat_watchers_personalized(
        chat,
        lambda context: {
            "type": "conversation_update",
            "payload": conversation_operational_payload(chat, user=context),
        },
    )


def _handle_operation_exception(
    db: Session,
    *,
    error: Exception,
    log_key: str,
    default_message: str,
    extra: dict | None = None,
) -> None:
    rollback_safely(db)

    if isinstance(error, HTTPException):
        raise error

    if isinstance(error, OperationalError):
        logger.exception(log_key, extra=extra or {})
        raise HTTPException(503, default_message)

    if isinstance(error, SQLAlchemyError):
        logger.exception(log_key, extra=extra or {})
        raise HTTPException(500, default_message)

    logger.exception(log_key, extra=extra or {})
    raise HTTPException(500, default_message)


@router.websocket("/ws", dependencies=[Depends(enforce_panel_ws_origin)])
async def websocket_endpoint(websocket: WebSocket):
    session_token = websocket.cookies.get(panel_session_cookie_name())
    if not session_token:
        await websocket.close(code=1008)
        return

    db_gen = get_db()
    db = next(db_gen)

    try:
        user = decode_panel_session(session_token, db)
    except Exception:
        await websocket.close(code=1008)
        try:
            db.close()
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        return

    allowed_empresa_id = int(getattr(settings, "PANEL_ALLOWED_EMPRESA_ID", 1) or 1)
    if int(user.empresa_id or 0) != allowed_empresa_id:
        logger.warning(
            "panel_ws_empresa_denied",
            extra={
                "username": getattr(user, "username", None),
                "role": getattr(user, "role", None),
                "empresa_id": getattr(user, "empresa_id", None),
                "allowed_empresa_id": allowed_empresa_id,
            },
        )
        await websocket.close(code=1008)
        try:
            db.close()
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        return

    await websocket.accept()
    websocket.state.user = user
    last_typing_at = datetime.min

    try:
        await manager.connect(websocket, user)

        while True:
            raw_data = await websocket.receive_text()
            if len(raw_data) > 4096:
                await websocket.close(code=1009)
                return

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.close(code=1003)
                return

            if payload.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "server_time": datetime.utcnow().isoformat(),
                })
                continue

            if payload.get("type") != "typing":
                continue

            now = datetime.utcnow()
            if (now - last_typing_at).total_seconds() < 1:
                continue

            last_typing_at = now
            session_id = payload.get("session_id")
            chat = None

            if session_id:
                chat = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

            if chat and can_view_chat(chat, user):
                await manager.send_to_chat_watchers(chat, {
                    "type": "typing",
                    "session_id": session_id,
                    "username": user.username,
                })
            elif not chat:
                await manager.send_to_role(normalize_role(user.role), {
                    "type": "typing",
                    "session_id": session_id,
                    "username": user.username,
                })

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        logger.exception("panel_websocket_failed")
        await manager.disconnect(websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        try:
            db.close()
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass


@router.post("/conversations/{session_id}/read", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def mark_as_read(
    session_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .with_for_update()
        .first()
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    initialize_operational_defaults(session)
    ensure_can_view_chat(session, user)

    session.unread_count = 0
    db.commit()

    await manager.send_to_chat_watchers(session, {
        "type": "update_unread",
        "session_id": session.id,
        "unread_count": 0,
    })

    return {"status": "ok"}


@router.get("/dashboard/state-times")
def dashboard_state_times(
    days: int = 7,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    date_from = datetime.utcnow() - timedelta(days=days)

    events = (
        apply_chat_visibility_filter(
            db.query(
                FlowEvent.session_id,
                FlowEvent.from_state,
                FlowEvent.to_state,
                FlowEvent.created_at,
            ),
            user,
        )
        .join(ChatSessions, FlowEvent.session_id == ChatSessions.id)
        .filter(
            FlowEvent.created_at >= date_from,
            FlowEvent.from_state.isnot(None),
            FlowEvent.to_state.isnot(None),
        )
        .order_by(FlowEvent.session_id, FlowEvent.created_at)
        .all()
    )

    transitions: dict[str, dict] = {}
    last_event_per_session: dict[int, object] = {}

    for event in events:
        session_id = event.session_id
        if session_id in last_event_per_session:
            previous = last_event_per_session[session_id]
            key = f"{previous.to_state} → {event.to_state}"
            time_diff = (event.created_at - previous.created_at).total_seconds()

            if key not in transitions:
                transitions[key] = {
                    "from_state": previous.to_state,
                    "to_state": event.to_state,
                    "times": [],
                }

            if 0 < time_diff < 86400:
                transitions[key]["times"].append(time_diff)

        last_event_per_session[session_id] = event

    result = []
    for key, data in transitions.items():
        times = data["times"]
        if not times:
            continue

        avg_time = sum(times) / len(times)
        result.append({
            "transition": key,
            "from_state": data["from_state"],
            "to_state": data["to_state"],
            "count": len(times),
            "avg_seconds": round(avg_time, 2),
            "avg_minutes": round(avg_time / 60, 2),
            "max_minutes": round(max(times) / 60, 2),
            "min_minutes": round(min(times) / 60, 2),
        })

    result_sorted = sorted(result, key=lambda item: item["avg_seconds"], reverse=True)
    return {"range_days": days, "data": result_sorted}


@router.get("/dashboard/funnel")
def dashboard_funnel(
    days: int = 7,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    date_from = datetime.utcnow() - timedelta(days=days)

    events = (
        apply_chat_visibility_filter(
            db.query(
                FlowEvent.session_id,
                FlowEvent.to_state,
                FlowEvent.created_at,
            ),
            user,
        )
        .join(ChatSessions, FlowEvent.session_id == ChatSessions.id)
        .filter(
            FlowEvent.to_state.isnot(None),
            FlowEvent.created_at >= date_from,
        )
        .all()
    )

    step_index = {step: index for index, step in enumerate(FUNNEL_STEPS)}
    session_max_index: dict[int, int] = {}

    for event in events:
        step = STEP_MAP.get(event.to_state)
        if step not in step_index:
            continue

        current_index = step_index[step]
        previous_index = session_max_index.get(event.session_id, -1)
        if current_index > previous_index:
            session_max_index[event.session_id] = current_index

    sessions = (
        apply_chat_visibility_filter(db.query(ChatSessions), user)
        .filter(
            ChatSessions.last_message_at >= date_from,
            ChatSessions.folio.isnot(None),
        )
        .all()
    )

    for session in sessions:
        step = resolve_panel_current_step(session, None)
        if step not in step_index:
            continue

        current_index = step_index[step]
        previous_index = session_max_index.get(session.id, -1)
        if current_index > previous_index:
            session_max_index[session.id] = current_index

    step_counts = {step: 0 for step in FUNNEL_STEPS}
    for max_index in session_max_index.values():
        for step in FUNNEL_STEPS[: max_index + 1]:
            step_counts[step] += 1

    funnel = []
    for step in FUNNEL_STEPS:
        funnel.append({
            "step": step,
            "total": step_counts.get(step, 0),
        })

    for index in range(len(funnel)):
        current = funnel[index]["total"]
        next_val = funnel[index + 1]["total"] if index + 1 < len(funnel) else 0
        funnel[index]["drop_off"] = max(current - next_val, 0)
        funnel[index]["conversion_pct"] = round((next_val / current * 100) if current > 0 else 0, 2)

    return {"range_days": days, "data": funnel}


@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    visible_session_ids_subq = apply_chat_visibility_filter(db.query(ChatSessions.id), user).subquery()
    visible_session_ids = select(visible_session_ids_subq.c.id)

    total_sessions = apply_chat_visibility_filter(
        db.query(func.count(ChatSessions.id)),
        user,
    ).scalar()

    active_sessions = (
        apply_chat_visibility_filter(db.query(func.count(ChatSessions.id)), user)
        .filter(ChatSessions.last_message_at >= func.now() - text("INTERVAL 1 DAY"))
        .scalar()
    )

    total_messages_in = (
        db.query(func.count(Message.id))
        .filter(Message.direction == "in", Message.session_id.in_(visible_session_ids))
        .scalar()
    )

    total_messages_out = (
        db.query(func.count(Message.id))
        .filter(Message.direction.in_(["out", "agent"]), Message.session_id.in_(visible_session_ids))
        .scalar()
    )

    issues_open = (
        apply_chat_visibility_filter(
            db.query(func.count(Inconsistencias.id)).join(ChatSessions, ChatSessions.id == Inconsistencias.session_id),
            user,
        )
        .filter(func.lower(Inconsistencias.estatus) == "abierta")
        .scalar()
    )

    return {
        "total_sessions": total_sessions or 0,
        "active_sessions": active_sessions or 0,
        "messages_in": total_messages_in or 0,
        "messages_out": total_messages_out or 0,
        "issues_open": issues_open or 0,
    }


@router.get("/verifications")
def get_verifications(
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    valid_statuses = {None, "in_progress", "inconsistent", "human_required", "stalled", "completed"}
    if status not in valid_statuses:
        raise HTTPException(400, "status inválido")
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit inválido")
    if offset < 0:
        raise HTTPException(400, "offset inválido")

    sessions_query = (
        apply_chat_visibility_filter(db.query(ChatSessions), user)
        .filter(ChatSessions.folio.isnot(None))
        .order_by(ChatSessions.last_message_at.desc())
    )

    total = (
        apply_chat_visibility_filter(db.query(func.count(ChatSessions.id)), user)
        .filter(ChatSessions.folio.isnot(None))
        .scalar()
    )

    sessions = sessions_query.all() if status else sessions_query.offset(offset).limit(limit).all()
    if not sessions:
        return {"data": [], "total": 0 if status else total, "has_more": False}

    phone_to_name = resolve_names_by_phone(db, sessions, empresa_id=user.empresa_id)
    folios = [str(session.folio) for session in sessions if session.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    no_cuentas = [value for value in folio_to_no_cuenta.values() if value is not None]
    verification_map: dict[str, VerificacionCuenta] = {}
    if no_cuentas:
        verificaciones = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta.in_(no_cuentas))
            .all()
        )
        verification_map = {
            str(verification.no_cuenta): verification
            for verification in verificaciones
            if verification.no_cuenta
        }

    inconsistencias = db.query(Inconsistencias).filter(Inconsistencias.folio.in_(folios)).all()
    inconsistencias_by_folio = group_inconsistencias_by_folio(inconsistencias)

    result = []
    for session in sessions:
        folio = str(session.folio)
        no_cuenta = folio_to_no_cuenta.get(folio)
        verification = verification_map.get(no_cuenta) if no_cuenta else None
        progress = verification.json if verification else {}
        verification_data = compute_verification(progress)

        current_step = resolve_panel_current_step(session, verification_data["current_step"])
        inconsistencias_folio = inconsistencias_by_folio.get(folio, [])
        serialized_inconsistencias = serialize_inconsistencias(inconsistencias_folio)
        open_inconsistencia = has_open_inconsistencia(serialized_inconsistencias)
        panel_status = classify_panel_status(
            verification_data=verification_data,
            has_open_inconsistencia=open_inconsistencia,
            last_activity=session.last_message_at,
            requires_human=False,
        )
        inconsistencia_summary = summarize_inconsistencias(serialized_inconsistencias)

        item = {
            "session_id": session.id,
            "folio": folio,
            "name": phone_to_name.get(normalize_phone(session.phone)),
            "no_cuenta": no_cuenta,
            "phone": session.phone,
            "status": panel_status,
            "progress_pct": verification_data["progress_pct"],
            "current_step": current_step,
            "inconsistencias": serialized_inconsistencias,
            "inconsistencias_count": inconsistencia_summary["severity_counts"]["total"],
            "severity_counts": inconsistencia_summary["severity_counts"],
            "highest_severity": inconsistencia_summary["highest_severity"],
            "confirmed_count": verification_data["progress_count"],
            "total_steps": verification_data["total_steps"],
            "last_activity": session.last_message_at,
            "siga_url": build_siga_url(no_cuenta, folio),
        }

        if status and item["status"] != status:
            continue

        result.append(item)

    if status:
        filtered_total = len(result)
        paginated_result = result[offset : offset + limit]
        return {
            "data": paginated_result,
            "total": filtered_total,
            "has_more": (offset + len(paginated_result)) < filtered_total,
        }

    return {
        "data": result,
        "total": total,
        "has_more": (offset + len(result)) < total,
    }


def build_verification_detail_sync(session_id: int, db: Session, user) -> dict:
    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()
    if not session or not session.folio:
        raise HTTPException(404, "Verificación no encontrada")

    initialize_operational_defaults(session)
    ensure_can_view_chat(session, user)

    folio = str(session.folio)
    service = VerificationService(db)
    no_cuenta = service.resolve_no_cuenta_from_folio(str(session.folio)) if session.folio else None

    verification = None
    progress = {}
    if no_cuenta:
        verification = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .first()
        )
    if verification:
        progress = verification.json or {}

    verification_data = compute_verification(progress)
    inconsistencias = db.query(Inconsistencias).filter(Inconsistencias.folio == folio).all()
    serialized_inconsistencias = serialize_inconsistencias(inconsistencias)
    inconsistencia_summary = summarize_inconsistencias(serialized_inconsistencias)
    open_inconsistencia = any(item["estado"] == "ABIERTA" for item in serialized_inconsistencias)

    panel_status = classify_panel_status(
        verification_data=verification_data,
        has_open_inconsistencia=open_inconsistencia,
        last_activity=session.last_message_at,
        requires_human=False,
    )

    current_step = resolve_panel_current_step(session, verification_data["current_step"])

    return {
        "session_id": session.id,
        "folio": folio,
        "name": None,
        "no_cuenta": no_cuenta,
        "phone": session.phone,
        "status": panel_status,
        "progress_pct": verification_data["progress_pct"],
        "current_step": current_step,
        "inconsistencias": serialized_inconsistencias,
        "inconsistencias_count": inconsistencia_summary["severity_counts"]["total"],
        "severity_counts": inconsistencia_summary["severity_counts"],
        "highest_severity": inconsistencia_summary["highest_severity"],
        "confirmed_count": verification_data["progress_count"],
        "total_steps": verification_data["total_steps"],
        "last_activity": session.last_message_at,
        "siga_url": build_siga_url(no_cuenta, folio),
    }


@router.get("/verifications/{session_id}")
async def get_verification_by_session(
    session_id: int,
    refresh_siga: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    item = await run_in_threadpool(build_verification_detail_sync, session_id, db, user)

    if normalize_role(user.role) in {"admin", "jefe_operativo"}:
        return await enrich_verification_with_bridge(
            item,
            company_id=user.empresa_id,
            bypass_cache=refresh_siga,
        )

    return item


@router.patch("/inconsistencias/{inconsistencia_id}/resolution", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def update_inconsistencia_panel_resolution(
    inconsistencia_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    if normalize_role(user.role) == "lectura":
        raise HTTPException(403, "No autorizado")

    payload = await request.json()
    if "resolved_by_panel" not in payload or not isinstance(payload["resolved_by_panel"], bool):
        raise HTTPException(400, "resolved_by_panel booleano requerido")

    ui_id = payload.get("ui_id")
    panel_resolved = bool(payload["resolved_by_panel"])

    existing_inc = db.query(Inconsistencias).filter(Inconsistencias.id == inconsistencia_id).first()
    if not existing_inc:
        raise HTTPException(404, "Inconsistencia no encontrada")

    if existing_inc.session_id:
        inc_session = db.query(ChatSessions).filter(ChatSessions.id == existing_inc.session_id).first()
        if inc_session:
            initialize_operational_defaults(inc_session)
            ensure_can_view_chat(inc_session, user)

    was_open = bool(existing_inc and str(existing_inc.estatus or "").upper() == "ABIERTA")

    try:
        inc = mark_panel_resolution(
            db=db,
            inconsistencia_id=inconsistencia_id,
            resolved=panel_resolved,
            ui_id=ui_id,
        )
    except ValueError:
        raise HTTPException(404, "Inconsistencia no encontrada")

    db.commit()
    db.refresh(inc)

    is_open = str(inc.estatus or "").upper() == "ABIERTA"
    issues_open_delta = int(is_open) - int(was_open)
    verification_snapshot = None
    session = None

    if inc.session_id:
        session = db.query(ChatSessions).filter(ChatSessions.id == inc.session_id).first()
        if session:
            initialize_operational_defaults(session)
            verification_snapshot = build_verification_snapshot(db, session)

            if verification_snapshot:
                await manager.send_to_chat_watchers(session, {
                    "type": "verification_update",
                    "payload": verification_snapshot,
                })

            await manager.send_to_chat_watchers(session, {
                "type": "inconsistencia_updated",
                "payload": {
                    "id": inc.id,
                    "ui_id": ui_id,
                    "session_id": inc.session_id,
                    "resolved_by_panel": panel_resolved,
                    "resolved_by_siga": bool(inc.resolved_by_siga),
                },
            })

    if issues_open_delta:
        dashboard_sender = manager.send_to_admins if session and session.test_mode else manager.send_to_all
        await dashboard_sender({
            "type": "dashboard_update",
            "payload": {"issues_open_delta": issues_open_delta},
        })

    return {
        "id": inc.id,
        "ui_id": ui_id,
        "session_id": inc.session_id,
        "resolved_by_panel": panel_resolved,
        "resolved_by_siga": bool(inc.resolved_by_siga),
        "verification": verification_snapshot,
    }


@router.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    limit: int = DEFAULT_CONVERSATIONS_LIMIT,
    offset: int = 0,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    limit = max(1, min(int(limit or DEFAULT_CONVERSATIONS_LIMIT), MAX_CONVERSATIONS_LIMIT))
    offset = max(0, int(offset or 0))

    sessions = (
        apply_chat_visibility_filter(db.query(ChatSessions), user)
        .order_by(desc(ChatSessions.last_message_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    phone_to_name = resolve_names_by_phone(db, sessions, empresa_id=user.empresa_id)
    folios = [str(session.folio) for session in sessions if session.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    return [
        build_conversation_response(
            session,
            user=user,
            name=phone_to_name.get(normalize_phone(session.phone)),
            no_cuenta=folio_to_no_cuenta.get(str(session.folio)) if session.folio else None,
        )
        for session in sessions
    ]


@router.get("/gestores-disponibles", response_model=list[AvailableManagerResponse])
def get_gestores_disponibles(
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    require_permission(user, "chat:assign_manager")
    try:
        managers = get_available_managers(db, empresa_id=user.empresa_id)
    except HTTPException:
        raise
    except OperationalError:
        logger.exception("panel_available_managers_db_failed", extra={"username": user.username})
        raise HTTPException(503, "No se pudo consultar la lista de gestores")
    except SQLAlchemyError:
        logger.exception("panel_available_managers_query_failed", extra={"username": user.username})
        raise HTTPException(500, "No se pudo consultar la lista de gestores")
    except Exception:
        logger.exception("panel_available_managers_unexpected_failed", extra={"username": user.username})
        raise HTTPException(500, "No se pudo construir la lista de gestores")

    return [
        AvailableManagerResponse(
            username=item.username,
            nombre=item.nombre,
            jefe_directo=item.jefe_directo,
            puesto=item.puesto,
            current_load=item.current_load,
            is_online=item.is_online,
            duplicate_rows=item.duplicate_rows,
        )
        for item in managers
    ]


@router.post(
    "/chats/{session_id}/assign-manager",
    response_model=ConversationResponse,
    dependencies=HTTP_ORIGIN_DEPENDENCIES,
)
async def assign_manager_to_chat(
    session_id: int,
    payload: AssignManagerRequest,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = assign_chat_to_manager(
            db,
            session_id=session_id,
            actor=user,
            manager_username=payload.username,
            reason=payload.reason,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user)
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_assign_manager_failed",
            default_message="No se pudo asignar el gestor",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/maintenance/reassign-inactive-managers", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def reassign_inactive_managers_endpoint(
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        results = reassign_inactive_manager_chats(db, actor=user)
        db.commit()
        for result in results:
            await publish_chat_operation(result)
        return {"updated": len(results)}
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_reassign_inactive_managers_failed",
            default_message="No se pudieron reasignar los chats de gestores inactivos",
            extra={"username": user.username},
        )


@router.get("/messages/{session_id}", response_model=PaginatedMessagesResponse)
def get_messages(
    session_id: int,
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    limit = min(max(1, int(limit or 30)), MAX_MESSAGES_LIMIT)
    offset = max(0, int(offset or 0))

    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()
    if not session:
        raise HTTPException(404, "La sesión no existe")

    initialize_operational_defaults(session)
    ensure_can_view_chat(session, user)

    base_query = db.query(Message).filter(Message.session_id == session_id)
    total = base_query.count()

    messages = (
        base_query
        .order_by(desc(Message.id))
        .offset(offset)
        .limit(limit)
        .all()
    )
    messages.reverse()

    return PaginatedMessagesResponse(
        data=[
            MessageResponse(
                id=message.id,
                direction=message.direction,
                content=message.content,
                created_at=message.created_at,
                type=message.type,
                media_url=message.media_url,
                file_name=message.file_name,
            )
            for message in messages
        ],
        total=total,
        has_more=(offset + len(messages)) < total,
    )


@router.post("/conversations/{session_id}/take", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def take_conversation(
    session_id: int,
    payload: TakeChatRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = tomar_chat(
            db,
            session_id=session_id,
            actor=user,
            target_role=payload.target_role if payload else None,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_take_conversation_failed",
            default_message="No se pudo tomar la conversación",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/conversations/{session_id}/release", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def release_conversation(
    session_id: int,
    payload: OperationReasonRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = liberar_chat(
            db,
            session_id=session_id,
            actor=user,
            reason=payload.reason if payload else None,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_release_conversation_failed",
            default_message="No se pudo liberar la conversación",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/conversations/{session_id}/transfer", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def transfer_conversation(
    session_id: int,
    payload: TransferChatRequest,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = transferir_chat(
            db,
            session_id=session_id,
            actor=user,
            destination=payload.destination,
            destination_user_id=payload.destination_user_id,
            reason=payload.reason,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_transfer_conversation_failed",
            default_message="No se pudo transferir la conversación",
            extra={"session_id": session_id, "username": user.username, "destination": payload.destination},
        )


@router.post("/conversations/{session_id}/return/assistant", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def return_conversation_to_assistant(
    session_id: int,
    payload: OperationReasonRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = send_to_assistant(
            db,
            session_id=session_id,
            actor=user,
            reason=payload.reason if payload else None,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_return_to_assistant_failed",
            default_message="No se pudo devolver la conversación al assistant",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/conversations/{session_id}/return/gestor", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def return_conversation_to_gestor(
    session_id: int,
    payload: OperationReasonRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = devolver_a_gestor(
            db,
            session_id=session_id,
            actor=user,
            destination_user_id=payload.destination_user_id if payload else None,
            reason=payload.reason if payload else None,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_return_to_gestor_failed",
            default_message="No se pudo devolver la conversación al gestor",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/conversations/{session_id}/return/soporte", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def return_conversation_to_soporte(
    session_id: int,
    payload: OperationReasonRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = devolver_a_soporte(
            db,
            session_id=session_id,
            actor=user,
            destination_user_id=payload.destination_user_id if payload else None,
            reason=payload.reason if payload else None,
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_return_to_soporte_failed",
            default_message="No se pudo devolver la conversación a soporte",
            extra={"session_id": session_id, "username": user.username},
        )


@router.post("/conversations/bulk-reassign", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def bulk_reassign_conversations(
    payload: BulkReassignRequest,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        results = reasignacion_masiva(
            db,
            session_ids=payload.session_ids,
            actor=user,
            destination=payload.destination,
            destination_user_id=payload.destination_user_id,
            reason=payload.reason,
        )
        db.commit()
        for result in results:
            await publish_chat_operation(result)
        return {"updated": len(results)}
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_bulk_reassign_failed",
            default_message="No se pudo completar la reasignación masiva",
            extra={"username": user.username},
        )


@router.post("/conversations/{session_id}/technical/close", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def close_technical_conversation_incident(
    session_id: int,
    payload: CloseSupportTicketRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    try:
        result = close_support_ticket(
            db,
            session_id=session_id,
            actor=user,
            resolution=payload.resolution if payload else None,
            return_action=payload.return_action if payload else "return_to_original_gestor",
            fallback_destination=payload.fallback_destination if payload else "jefe_operativo",
        )
        db.commit()
        await publish_chat_operation(result)
        return build_conversation_response(result.chat, user=user).dict()
    except Exception as error:
        _handle_operation_exception(
            db,
            error=error,
            log_key="panel_close_technical_failed",
            default_message="No se pudo cerrar la incidencia técnica",
            extra={"session_id": session_id, "username": user.username},
        )


@router.get("/technical/metrics")
def get_technical_metrics(
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    require_permission(user, "metrics:view")
    return technical_ticket_metrics(db)


@router.get("/feature-flags")
def list_feature_flags(
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    require_permission(user, "testing:use")
    rows = db.query(PanelFeatureFlag).order_by(PanelFeatureFlag.name.asc()).all()
    return [
        {
            "name": row.name,
            "enabled": bool(row.enabled),
            "description": row.description,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.patch("/feature-flags/{name}", dependencies=HTTP_ORIGIN_DEPENDENCIES)
def update_feature_flag(
    name: str,
    payload: FeatureFlagUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    require_permission(user, "feature_flags:write")
    if not FEATURE_FLAG_NAME_RE.fullmatch(name):
        raise HTTPException(400, "Nombre de flag invalido")

    flag = db.query(PanelFeatureFlag).filter(PanelFeatureFlag.name == name).first()
    if not flag:
        flag = PanelFeatureFlag(name=name)
        db.add(flag)

    flag.enabled = payload.enabled
    flag.description = payload.description
    flag.updated_by = user.username
    flag.updated_at = datetime.utcnow()
    db.commit()

    return {
        "name": flag.name,
        "enabled": bool(flag.enabled),
        "description": flag.description,
        "updated_by": flag.updated_by,
        "updated_at": flag.updated_at,
    }


@router.post("/messages", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def send_agent_message(
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "Mensaje vacío")
    if len(content) > 1000:
        raise HTTPException(400, "Mensaje demasiado largo")

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == payload.session_id)
        .with_for_update()
        .first()
    )
    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    initialize_operational_defaults(session)
    ensure_can_reply_chat(session, user)

    phone = session.phone
    now = datetime.utcnow()

    try:
        await send_whatsapp_message(phone, content)

        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
        )
        db.add(message)

        session.last_message = content
        session.last_message_at = now
        session.last_agent_message_at = now
        session.unread_count = 0

        db.commit()
        db.refresh(message)
    except HTTPException:
        rollback_safely(db)
        raise
    except Exception:
        rollback_safely(db)
        logger.exception(
            "panel_send_message_failed",
            extra={"session_id": payload.session_id, "username": user.username},
        )
        raise HTTPException(502, "No se pudo enviar mensaje a WhatsApp")

    await manager.send_to_chat_watchers_personalized(
        session,
        lambda context: {
            "type": "new_message",
            "session_id": session.id,
            "phone": session.phone,
            "conversation": {
                "id": session.id,
                "phone": session.phone,
                "last_message": content,
                "last_message_at": now.isoformat(),
                "unread_count": 0,
                **conversation_operational_payload(session, user=context),
            },
            "message": {
                "id": message.id,
                "content": content,
                "direction": "agent",
                "created_at": now.isoformat(),
            },
        },
    )

    return {"status": "sent"}


@router.post("/messages/file", dependencies=HTTP_ORIGIN_DEPENDENCIES)
async def send_agent_file(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_empresa_panel),
):
    payload = await request.json()

    session_id = payload.get("session_id")
    media_url = payload.get("media_url")
    file_name = payload.get("file_name")
    media_type = payload.get("type")

    if not session_id or not media_url or not media_type:
        raise HTTPException(400, "Datos incompletos")

    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()
    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    initialize_operational_defaults(session)
    ensure_can_reply_chat(session, user)

    phone = session.phone
    was_active = bool(
        session.last_message_at
        and session.last_message_at >= datetime.utcnow() - timedelta(days=1)
    )

    content = payload.get("content")
    if not content or content == "[MEDIA]":
        content = " "

    last_message = content.strip() if content and content.strip() else "Archivo adjunto"
    now = datetime.utcnow()

    try:
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
            type=media_type,
            media_url=media_url,
            file_name=file_name,
        )

        db.add(message)
        session.last_message = last_message
        session.last_message_at = now
        session.last_agent_message_at = now
        session.unread_count = 0

        db.commit()
        db.refresh(message)
    except Exception:
        rollback_safely(db)
        logger.exception("panel_file_message_db_failed", extra={"session_id": session_id})
        raise HTTPException(500, "Error guardando mensaje")

    await manager.send_to_chat_watchers_personalized(
        session,
        lambda context: {
            "type": "new_message",
            "session_id": session.id,
            "phone": session.phone,
            "conversation": {
                "id": session.id,
                "phone": session.phone,
                "name": None,
                "last_message": last_message,
                "last_message_at": message.created_at.isoformat(),
                "unread_count": 0,
                "folio": str(session.folio) if session.folio else None,
                **conversation_operational_payload(session, user=context),
            },
            "message": {
                "id": message.id,
                "phone": session.phone,
                "content": message.content,
                "direction": "agent",
                "type": media_type,
                "media_url": media_url,
                "file_name": file_name,
                "created_at": message.created_at.isoformat(),
            },
            "unread_count": 0,
        },
    )

    dashboard_sender = manager.send_to_admins if session.test_mode else manager.send_to_all
    await dashboard_sender({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "active_sessions_delta": 0 if was_active else 1,
        },
    })

    verification_sender = manager.send_to_admins if session.test_mode else manager.send_to_all
    snapshot = build_verification_snapshot(db, session)
    if snapshot:
        await verification_sender({
            "type": "verification_update",
            "payload": snapshot,
        })
    else:
        await verification_sender({
            "type": "verification_update",
            "payload": {
                "session_id": session.id,
                "last_activity": now.isoformat(),
            },
        })

    async def send_media_safe():
        try:
            caption = message.content if message.content else None
            await send_whatsapp_media(
                phone=phone,
                media_url=media_url,
                media_type=media_type,
                caption=caption,
                filename=file_name,
            )
        except Exception:
            logger.exception("panel_file_message_whatsapp_failed", extra={"session_id": session.id})

    asyncio.create_task(send_media_safe())
    return {"status": "sent"}
