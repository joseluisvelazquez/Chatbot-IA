from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc, func, text
from datetime import datetime, timedelta

from app.schemas.panel import (
    SendMessageRequest,
    ConversationResponse,
    MessageResponse,
    PaginatedMessagesResponse
)

from app.adapters.whatsapp_client import _extract_meta_message_id, send_whatsapp_message
from app.db.session import get_db
from app.security.auth_service import (
    decode_panel_session,
    is_allowed_panel_company,
    restrict_to_assigned,
)
from app.services.verification_service import VerificationService
from app.websockets.manager import manager
from app.db.models import VerificacionCuenta, ChatSessions, Inconsistencias, Message, FlowEvent
from app.security.auth_dependencies import get_current_panel_user
from app.adapters.whatsapp_client import send_whatsapp_media
from fastapi import Request
from app.core.verification_steps import STEP_ORDER
from app.services.verification_tracker import STEP_MAP
from app.utils.inconsistencias_serializer import (
    serialize_inconsistencias,
    summarize_inconsistencias,
)
from app.services.verification_panel_service import (
    build_verification_snapshot,
    classify_panel_status,
    compute_verification,
    group_inconsistencias_by_folio,
    has_open_inconsistencia,
    merge_progress_from_flow_events,
    resolve_panel_current_step,
)
from app.utils.timezone import mexico_now_naive
from app.services.inconsistencias_service import mark_panel_resolution
from app.services.collections_panel_service import (
    build_collection_filters,
    can_filter_collections_by_gestor,
    can_view_collections,
    get_collection_detail,
    get_collection_payments,
    list_collection_managers,
    list_collections,
)
from app.services.siga_bridge_cache import (
    apply_siga_snapshot_to_panel_item,
    get_cached_verification,
    get_cached_verification_row,
    get_or_fetch_verification,
    is_cache_valid,
)
from app.services.siga_navigation import build_siga_account_url
from app.services.ws_events import (
    build_conversation_updated_event,
    build_inconsistency_updated_event,
    build_new_message_event,
    build_siga_snapshot_updated_event,
    build_verification_updated_event,
    minimal_verification_payload,
)
from app.db.models import BitacoraVentas
from app.config.settings import settings
from app.services.message_metadata import (
    build_outgoing_interactive_metadata,
    build_outgoing_media_metadata,
    merge_message_metadata,
)
from app.services.message_reaction_service import attach_reactions_to_messages

# ORDEN REAL DEL FLOW 
FUNNEL_STEPS = STEP_ORDER
router = APIRouter(
    prefix="/api/panel",
    tags=["panel"]
)
logger = logging.getLogger(__name__)


def build_siga_url(no_cuenta: str | None, folio: str | None) -> str | None:
    return build_siga_account_url(no_cuenta, folio)


def redact_siga_details_for_role(item: dict, role: str | None) -> dict:
    if role in ("admin", "jefe_operativo", "sistemas"):
        return item

    siga = item.get("siga") if isinstance(item.get("siga"), dict) else None
    if siga:
        item["siga"] = {
            "available": bool(siga.get("available")),
            "fetched_at": siga.get("fetched_at"),
            "source_table": siga.get("source_table"),
            "cache_valid": siga.get("cache_valid"),
        }

    bridge = item.get("siga_bridge") if isinstance(item.get("siga_bridge"), dict) else None
    if bridge:
        item["siga_bridge"] = {
            "enabled": bool(bridge.get("enabled")),
            "available": bool(bridge.get("available")),
            "status": bridge.get("status"),
            "source": bridge.get("source"),
            "updated_at": bridge.get("updated_at"),
        }

    return item


def require_company_scope(user) -> None:
    if not is_allowed_panel_company(user.empresa_id):
        raise HTTPException(403, "No autorizado")


def require_reply_permission(user) -> None:
    if user.role not in ("admin", "ventas", "cobranza", "jefe_operativo", "sistemas"):
        raise HTTPException(403, "No autorizado")


def require_collection_permission(user) -> None:
    if not can_view_collections(user):
        raise HTTPException(403, "No autorizado")


def scoped_session_query(db: Session, user):
    return restrict_to_assigned(db.query(ChatSessions), user, db)


def get_scoped_session_or_404(
    db: Session,
    user,
    session_id: int,
    *,
    detail: str = "Sesion no encontrada",
) -> ChatSessions:
    session = (
        scoped_session_query(db, user)
        .filter(ChatSessions.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, detail)
    return session


def scoped_session_ids_subquery(db: Session, user):
    return restrict_to_assigned(db.query(ChatSessions.id), user, db).subquery()


# =========================================
# Obtener Mensajes con el websocket
# =========================================
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    session_token = websocket.cookies.get("panel_session")

    if not session_token:
        await websocket.close(code=1008)
        return

    # crear sesión DB manual
    db = next(get_db())

    try:
        user = decode_panel_session(session_token, db)  
    except Exception:
        db.close()
        await websocket.close(code=1008)
        return

    await websocket.accept()
    websocket.state.user = user
    websocket.state.company_id = int(user.empresa_id)
    if user.role in ("admin", "sistemas", "jefe_operativo"):
        websocket.state.allowed_session_ids = None
    else:
        websocket.state.allowed_session_ids = {
            int(row.id)
            for row in restrict_to_assigned(db.query(ChatSessions.id), user, db).all()
            if getattr(row, "id", None) is not None
        }

    import json

    try:
        manager.connect(websocket)

        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("type") == "typing":
                try:
                    session_id = int(payload.get("session_id"))
                except (TypeError, ValueError):
                    continue
                allowed_session_ids = getattr(websocket.state, "allowed_session_ids", None)
                if allowed_session_ids is not None and session_id not in allowed_session_ids:
                    continue
                await manager.send_to_all({
                    "type": "typing",
                    "session_id": session_id
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket)

    except Exception:
        manager.disconnect(websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        db.close()  #importante
# =========================================
# Panel API: Marcar conversación como leída (RESET UNREAD COUNT)
# =========================================

@router.post("/conversations/{session_id}/read")
async def mark_as_read(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    require_company_scope(user)
    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada",
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    phone_key = normalize_conversation_phone(session.phone)
    sessions_to_mark = [session]
    if phone_key:
        sessions_to_mark = [
            row
            for row in scoped_session_query(db, user).all()
            if normalize_conversation_phone(row.phone) == phone_key
        ] or [session]

    for item in sessions_to_mark:
        item.unread_count = 0

    db.commit()

    for item in sessions_to_mark:
        await manager.send_to_all({
            "type": "update_unread",
            "session_id": item.id,
            "unread_count": 0
        })
    await manager.send_to_all(
        build_conversation_updated_event(
            session,
            patch={"unread_count": 0},
            source="panel_read",
        )
    )

    return {"status": "ok"}

def resolve_cuentas_from_folios(folios: list[str], db: Session, user) -> dict:
    require_company_scope(user)

    unique_folios = [str(folio) for folio in dict.fromkeys(folios) if folio]
    result = {folio: None for folio in unique_folios}

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

        no_cuenta = getattr(venta, "no_cuenta", None)
        if no_cuenta:
            result[folio] = str(no_cuenta)

    return result


def normalize_conversation_phone(phone: str | None) -> str:
    if not phone:
        return ""

    value = "".join(ch for ch in str(phone) if ch.isdigit())

    if value.startswith("52") and len(value) > 10:
        value = value[2:]

    return value[-10:]


def append_unique_text(items: list[str], value: str | None) -> None:
    if value is None:
        return

    text_value = str(value).strip()
    if text_value and text_value not in items:
        items.append(text_value)


def bridge_customer_name_from_snapshot(snapshot: dict | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    customer = snapshot.get("customer") if isinstance(snapshot.get("customer"), dict) else {}
    name = customer.get("name") or snapshot.get("name")
    text_value = str(name or "").strip()
    return text_value or None

# =========================================
# Endpoints para los dashboard (PAGINADO + DTO + LÓGICA DE NEGOCIO)
# =========================================

@router.get("/dashboard/state-times")
def dashboard_state_times(
    days: int = 7,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    scoped_session_ids = scoped_session_ids_subquery(db, user)
    # --------------------------------------
    # 🧠 FILTRO DE TIEMPO
    # --------------------------------------
    date_from = mexico_now_naive() - timedelta(days=days)

    # --------------------------------------
    #  SUBQUERY: ordenar eventos por sesión
    # --------------------------------------
    events = (
        db.query(
            FlowEvent.session_id,
            FlowEvent.from_state,
            FlowEvent.to_state,
            FlowEvent.created_at
        )
        .filter(
            FlowEvent.created_at >= date_from,
            FlowEvent.session_id.in_(db.query(scoped_session_ids.c.id)),
            FlowEvent.from_state.isnot(None),
            FlowEvent.to_state.isnot(None),
        )
        .order_by(FlowEvent.session_id, FlowEvent.created_at)
        .all()
    )

    # --------------------------------------
    # 🧠 CALCULAR TIEMPOS ENTRE TRANSICIONES
    # --------------------------------------
    transitions = {}

    last_event_per_session = {}

    for e in events:
        session_id = e.session_id

        if session_id in last_event_per_session:
            prev = last_event_per_session[session_id]

            # transición real
            key = f"{prev.to_state} → {e.to_state}"

            time_diff = (e.created_at - prev.created_at).total_seconds()

            if key not in transitions:
                transitions[key] = {
                    "from_state": prev.to_state,
                    "to_state": e.to_state,
                    "times": []
                }

            # evitar tiempos absurdos
            if 0 < time_diff < 86400:  # max 24h
                transitions[key]["times"].append(time_diff)

        last_event_per_session[session_id] = e

    # --------------------------------------
    #  AGREGAR MÉTRICAS
    # --------------------------------------
    result = []

    for key, data in transitions.items():
        times = data["times"]

        if not times:
            continue

        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)

        result.append({
            "transition": key,
            "from_state": data["from_state"],
            "to_state": data["to_state"],
            "count": len(times),
            "avg_seconds": round(avg_time, 2),
            "avg_minutes": round(avg_time / 60, 2),
            "max_minutes": round(max_time / 60, 2),
            "min_minutes": round(min_time / 60, 2),
        })

    # --------------------------------------
    #  ORDENAR POR TIEMPO PROMEDIO (cuellos de botella)
    # --------------------------------------
    result_sorted = sorted(result, key=lambda x: x["avg_seconds"], reverse=True)

    return {
        "range_days": days,
        "data": result_sorted
    }
@router.get("/dashboard/funnel")
def dashboard_funnel(
    days: int = 7,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    date_from = mexico_now_naive() - timedelta(days=days)
    scoped_session_ids = scoped_session_ids_subquery(db, user)
    sessions = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(
            ChatSessions.last_message_at >= date_from,
            ChatSessions.folio.isnot(None),
        )
        .all()
    )
    active_folio_by_session = {
        session.id: str(session.folio)
        for session in sessions
        if session.id and session.folio
    }

    events = (
        db.query(
            FlowEvent.session_id,
            FlowEvent.folio,
            FlowEvent.to_state,
            FlowEvent.created_at
        )
        .filter(
            FlowEvent.to_state.isnot(None),
            FlowEvent.created_at >= date_from,
            FlowEvent.session_id.in_(db.query(scoped_session_ids.c.id)),
        )
        .all()
    )

    # --------------------------------------
    # NORMALIZAR A STEPS
    # --------------------------------------
    step_index = {step: index for index, step in enumerate(FUNNEL_STEPS)}
    session_folio_max_index: dict[tuple[int, str], int] = {}

    for e in events:
        active_folio = active_folio_by_session.get(e.session_id)
        if not active_folio:
            continue

        event_folio = str(e.folio) if e.folio is not None else active_folio
        if event_folio != active_folio:
            continue

        step = STEP_MAP.get(e.to_state)

        if step not in step_index:
            continue

        key = (e.session_id, active_folio)
        current_index = step_index[step]
        previous_index = session_folio_max_index.get(key, -1)
        if current_index > previous_index:
            session_folio_max_index[key] = current_index

        # guardar primera vez que llegó al step

    for session in sessions:
        folio = str(session.folio)
        step = resolve_panel_current_step(session, None)
        if step not in step_index:
            continue

        key = (session.id, folio)
        current_index = step_index[step]
        previous_index = session_folio_max_index.get(key, -1)
        if current_index > previous_index:
            session_folio_max_index[key] = current_index

    # --------------------------------------
    # CONTAR USUARIOS POR STEP
    # --------------------------------------
    step_counts = {step: 0 for step in FUNNEL_STEPS}

    for max_index in session_folio_max_index.values():
        for step in FUNNEL_STEPS[:max_index + 1]:
            step_counts[step] += 1

    # --------------------------------------
    # CONSTRUIR FUNNEL ORDENADO
    # --------------------------------------
    funnel = []

    for step in FUNNEL_STEPS:
        funnel.append({
            "step": step,
            "total": step_counts.get(step, 0)
        })

    # --------------------------------------
    # DROP-OFF
    # --------------------------------------
    for i in range(len(funnel)):
        current = funnel[i]["total"]
        next_val = funnel[i + 1]["total"] if i + 1 < len(funnel) else 0

        funnel[i]["drop_off"] = max(current - next_val, 0)
        funnel[i]["conversion_pct"] = round(
            (next_val / current * 100) if current > 0 else 0,
            2
        )

    return {
        "range_days": days,
        "data": funnel
    }

@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),):

    require_company_scope(user)
    scoped_session_ids = scoped_session_ids_subquery(db, user)

    total_sessions = scoped_session_query(db, user).count()

    active_sessions = scoped_session_query(db, user)\
        .filter(ChatSessions.last_message_at >= func.now() - text("INTERVAL 1 DAY"))\
        .count()

    total_messages_in = db.query(func.count(Message.id))\
        .filter(
            Message.direction == "in",
            Message.session_id.in_(db.query(scoped_session_ids.c.id)),
        )\
        .scalar()

    total_messages_out = db.query(func.count(Message.id))\
        .filter(
            Message.direction.in_(["out", "agent"]),
            Message.session_id.in_(db.query(scoped_session_ids.c.id)),
        )\
        .scalar()

    inconsistencias_abiertas = restrict_to_assigned(db.query(Inconsistencias), user, db)\
        .filter(func.lower(Inconsistencias.estatus) == "abierta")\
        .count()

    return {
        "total_sessions": total_sessions or 0,
        "active_sessions": active_sessions or 0,
        "messages_in": total_messages_in or 0,
        "messages_out": total_messages_out or 0,
        "issues_open": inconsistencias_abiertas or 0
    }
# =========================================
# Obtener verificaciones (PAGINADO + DTO + LÓGICA DE NEGOCIO)
# =========================================

@router.get("/collections")
async def get_collections(
    no_cuenta: str | None = None,
    cuenta: str | None = None,
    folio: str | None = None,
    phone: str | None = None,
    telefono: str | None = None,
    name: str | None = None,
    nombre: str | None = None,
    cliente: str | None = None,
    status: str | None = None,
    classification: str | None = None,
    gestor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    overdue_only: bool = False,
    paid_only: bool = False,
    include_paid: bool = False,
    active_only: bool = True,
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    require_collection_permission(user)

    try:
        filters = build_collection_filters(
            account=no_cuenta or cuenta,
            folio=folio,
            phone=phone or telefono,
            name=name or nombre or cliente,
            status=status,
            classification=classification,
            gestor=gestor,
            date_from=date_from,
            date_to=date_to,
            overdue_only=overdue_only,
            paid_only=paid_only,
            include_paid=include_paid,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return await list_collections(db, user, filters)


@router.get("/collections/managers")
async def get_collection_managers_endpoint(
    search: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    require_collection_permission(user)
    if not can_filter_collections_by_gestor(user):
        raise HTTPException(403, "No autorizado")

    try:
        return await list_collection_managers(db, user, search=search, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/collections/{no_cuenta}/payments")
async def get_collection_payments_endpoint(
    no_cuenta: str,
    include_paid: bool = False,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    require_collection_permission(user)

    try:
        filters = build_collection_filters(account=no_cuenta, limit=1)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    payments = await get_collection_payments(
        db,
        user,
        filters.account or no_cuenta,
        include_paid=include_paid,
    )
    if payments is None:
        raise HTTPException(404, "Cuenta no encontrada")
    return {"data": payments, "total": len(payments)}


@router.get("/collections/{no_cuenta}")
async def get_collection_by_account(
    no_cuenta: str,
    include_paid: bool = False,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    require_collection_permission(user)

    try:
        filters = build_collection_filters(account=no_cuenta, limit=1)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    item = await get_collection_detail(
        db,
        user,
        filters.account or no_cuenta,
        include_paid=include_paid,
    )
    if not item:
        raise HTTPException(404, "Cuenta no encontrada")
    return item


@router.post("/collections/{no_cuenta}/refresh")
async def refresh_collection_by_account(
    no_cuenta: str,
    include_paid: bool = False,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)
    require_collection_permission(user)

    try:
        filters = build_collection_filters(account=no_cuenta, limit=1)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    item = await get_collection_detail(
        db,
        user,
        filters.account or no_cuenta,
        force_refresh=True,
        include_paid=include_paid,
    )
    if not item:
        raise HTTPException(404, "Cuenta no encontrada")
    return item


@router.get("/verifications")
def get_verifications(
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    # =========================
    # 🔐 VALIDACIONES
    # =========================
    require_company_scope(user)

    valid_statuses = {
        None,
        "in_progress",
        "inconsistent",
        "doubts",
        "calls",
        "human_required",
        "stalled",
        "completed",
    }

    if status not in valid_statuses:
        raise HTTPException(400, "status inválido")

    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit inválido")

    if offset < 0:
        raise HTTPException(400, "offset inválido")

    # =========================
    # 📦 OBTENER SESIONES
    # =========================
    
    sessions_query = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(ChatSessions.folio.isnot(None))
    )

    # 🕵️ Filtrar asesores
    if settings.ADVISOR_PHONES:
        sessions_query = sessions_query.filter(ChatSessions.phone.notin_(settings.ADVISOR_PHONES))

    sessions_query = sessions_query.order_by(ChatSessions.last_message_at.desc())

    total = sessions_query.order_by(None).count()

    sessions = (
        sessions_query.all()
        if status
        else sessions_query.offset(offset).limit(limit).all()
    )

    if not sessions:
        return {
            "data": [],
            "total": 0 if status else total,
            "has_more": False,
        }

    # =========================
    # 🧠 HELPERS
    # =========================
    # =========================
    # 📞 RESOLVER NOMBRES (BATCH)
    # =========================
    normalized_phones = list({
        normalize_conversation_phone(s.phone)
        for s in sessions
        if s.phone
    })

    ventas = (
        restrict_to_assigned(db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo), user, db)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == user.empresa_id
        )
        .all()
    )

    phone_to_name = {}
    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_conversation_phone(v.tel_1)
        if db_phone and v.nombre_completo:
            phone_to_name[db_phone] = v.nombre_completo.strip()

    # =========================
    # 🔗 FOLIOS → CUENTAS
    # =========================
    folios = [str(s.folio) for s in sessions if s.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)
    siga_snapshot_by_session: dict[int, dict | None] = {}
    siga_cache_row_by_session: dict[int, dict | None] = {}

    for session in sessions:
        folio_key = str(session.folio) if session.folio else None
        if not folio_key:
            continue
        cache_row = get_cached_verification_row(session, folio_key, allow_stale=True)
        snapshot_siga = cache_row.get("snapshot") if isinstance(cache_row, dict) else None
        if isinstance(snapshot_siga, dict):
            siga_snapshot_by_session[session.id] = snapshot_siga
            siga_cache_row_by_session[session.id] = cache_row
            if not folio_to_no_cuenta.get(folio_key) and snapshot_siga.get("no_cuenta"):
                folio_to_no_cuenta[folio_key] = str(snapshot_siga["no_cuenta"])

    no_cuentas = [
        nc for nc in folio_to_no_cuenta.values() if nc is not None
    ]

    verificaciones = []
    if no_cuentas:
        verificaciones = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta.in_(no_cuentas))
            .all()
        )

    verification_map = {
        str(v.no_cuenta): v
        for v in verificaciones
        if v.no_cuenta
    }

    # =========================
    # ⚠️ INCONSISTENCIAS (BATCH)
    # =========================
    inconsistencias = (
        restrict_to_assigned(db.query(Inconsistencias), user, db)
        .filter(Inconsistencias.folio.in_(folios))
        .all()
    )

    inconsistencias_by_folio = group_inconsistencias_by_folio(inconsistencias)

    # =========================
    # 🔄 ARMADO FINAL
    # =========================
    result = []

    for session in sessions:
        folio = str(session.folio)
        no_cuenta = folio_to_no_cuenta.get(folio)
        siga_snapshot = siga_snapshot_by_session.get(session.id)
        siga_cache_row = siga_cache_row_by_session.get(session.id)
        if not no_cuenta and isinstance(siga_snapshot, dict) and siga_snapshot.get("no_cuenta"):
            no_cuenta = str(siga_snapshot["no_cuenta"])

        verification = verification_map.get(no_cuenta) if no_cuenta else None
        progress = merge_progress_from_flow_events(
            db,
            session.id,
            verification.json if verification else {},
            current_state=session.state,
            folio=folio,
        )

        verification_data = compute_verification(progress)

        current_step = resolve_panel_current_step(
            session,
            verification_data["current_step"],
        )

        inconsistencias_folio = inconsistencias_by_folio.get(folio, [])

        serialized_inconsistencias = serialize_inconsistencias(inconsistencias_folio)
        open_inconsistencia = has_open_inconsistencia(serialized_inconsistencias)

        panel_status = classify_panel_status(
            verification_data=verification_data,
            has_open_inconsistencia=open_inconsistencia,
            last_activity=session.last_message_at,
            session_state=str(session.state or ""),
            previous_state=str(session.previous_state or ""),
        )

        inconsistencia_summary = summarize_inconsistencias(serialized_inconsistencias)

        item = {
            "session_id": session.id,
            "verification_id": getattr(verification, "id_verificacion", None) if verification else None,
            "folio": folio,
            "name": phone_to_name.get(normalize_conversation_phone(session.phone)),
            "no_cuenta": no_cuenta,
            "phone": session.phone,
            "status": panel_status,
            "session_state": str(session.state or ""),
            "previous_state": str(session.previous_state or ""),
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
        apply_siga_snapshot_to_panel_item(
            item,
            siga_snapshot,
            cache_valid=is_cache_valid(siga_cache_row, session=session) if siga_cache_row else None,
        )
        item["siga_url"] = build_siga_url(item.get("no_cuenta"), folio)
        redact_siga_details_for_role(item, getattr(user, "role", None))

        if status and item["status"] != status:
            continue

        result.append(item)

    if status:
        filtered_total = len(result)
        paginated_result = result[offset:offset + limit]

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
@router.get("/verifications/{session_id}")
async def get_verification_by_session(
    session_id: int,
    refresh_siga: bool = False,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    # =========================
    # 🔐 VALIDACIÓN
    # =========================
    require_company_scope(user)

    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Verificacion no encontrada",
    )

    if not session or not session.folio:
        raise HTTPException(404, "Verificación no encontrada")

    folio = str(session.folio)
    cached_siga_row = get_cached_verification_row(session, folio, allow_stale=True)
    cached_siga = cached_siga_row.get("snapshot") if isinstance(cached_siga_row, dict) else None

    # =========================
    # 🧠 RESOLVER no_cuenta
    # =========================
    service = VerificationService(db)

    no_cuenta = (
        service.resolve_no_cuenta_from_folio(str(session.folio), user.empresa_id)
        if session.folio
        else None
    )
    if not no_cuenta and isinstance(cached_siga, dict) and cached_siga.get("no_cuenta"):
        no_cuenta = str(cached_siga["no_cuenta"])


    # =========================
    # 🧾 VERIFICACIÓN
    # =========================
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

    progress = merge_progress_from_flow_events(
        db,
        session.id,
        progress,
        current_state=session.state,
        folio=folio,
    )

    verification_data = compute_verification(progress)

    # =========================
    # ⚠️ INCONSISTENCIAS
    # =========================
    inconsistencias = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.folio == folio)
        .all()
    )

    serialized_inconsistencias = serialize_inconsistencias(inconsistencias)
    inconsistencia_summary = summarize_inconsistencias(serialized_inconsistencias)

    open_inconsistencia = any(
        i["estado"] == "ABIERTA" for i in serialized_inconsistencias
    )

    # =========================
    # 📊 STATUS
    # =========================
    panel_status = classify_panel_status(
        verification_data=verification_data,
        has_open_inconsistencia=open_inconsistencia,
        last_activity=session.last_message_at,
        session_state=str(session.state or ""),
        previous_state=str(session.previous_state or ""),
    )

    # =========================
    # 🧠 STEP CORRECTO
    # =========================
    current_step = resolve_panel_current_step(
        session,
        verification_data["current_step"],
    )

    # =========================
    # 📦 RESPONSE FINAL
    # =========================
    item = {
        "session_id": session.id,
        "verification_id": getattr(verification, "id_verificacion", None) if verification else None,
        "folio": folio,
        "name": (
            cached_siga.get("customer", {}).get("name")
            if isinstance(cached_siga, dict) and isinstance(cached_siga.get("customer"), dict)
            else None
        ),
        "no_cuenta": no_cuenta,
        "phone": session.phone,

        "status": panel_status,
        "session_state": str(session.state or ""),
        "previous_state": str(session.previous_state or ""),
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
    if user.role in ("admin", "jefe_operativo", "sistemas"):
        fetched = False
        siga_snapshot = cached_siga
        siga_cache_row = cached_siga_row
        if refresh_siga or not isinstance(siga_snapshot, dict):
            siga_snapshot = await get_or_fetch_verification(
                session,
                folio,
                company_id=user.empresa_id,
                force_refresh=refresh_siga,
            )
            fetched = isinstance(siga_snapshot, dict)
            if fetched:
                db.commit()
                db.refresh(session)
                siga_cache_row = get_cached_verification_row(session, folio, allow_stale=True)

        apply_siga_snapshot_to_panel_item(
            item,
            siga_snapshot if isinstance(siga_snapshot, dict) else None,
            cache_valid=is_cache_valid(siga_cache_row, session=session) if siga_cache_row else None,
            refreshed=bool(refresh_siga and fetched),
        )
        if fetched and item.get("no_cuenta") and verification is None:
            refreshed_verification = (
                db.query(VerificacionCuenta)
                .filter(VerificacionCuenta.no_cuenta == item["no_cuenta"])
                .first()
            )
            if refreshed_verification:
                refreshed_progress = merge_progress_from_flow_events(
                    db,
                    session.id,
                    refreshed_verification.json or {},
                    current_state=session.state,
                    folio=folio,
                )
                refreshed_data = compute_verification(refreshed_progress)
                item.update(
                    {
                        "verification_id": getattr(refreshed_verification, "id_verificacion", None),
                        "progress_pct": refreshed_data["progress_pct"],
                        "current_step": resolve_panel_current_step(
                            session,
                            refreshed_data["current_step"],
                        ),
                        "status": classify_panel_status(
                            verification_data=refreshed_data,
                            has_open_inconsistencia=open_inconsistencia,
                            last_activity=session.last_message_at,
                            requires_human=False,
                        ),
                        "confirmed_count": refreshed_data["progress_count"],
                        "total_steps": refreshed_data["total_steps"],
                    }
                )
        item["siga_url"] = build_siga_url(item.get("no_cuenta"), folio)
        logger.info(
            "panel_siga_refresh_done" if refresh_siga else "panel_siga_snapshot_used",
            extra={
                "session_id": session.id,
                "folio": folio,
                "refresh_siga": refresh_siga,
                "available": (
                    bool(item.get("siga", {}).get("available"))
                    if isinstance(item.get("siga"), dict)
                    else False
                ),
            },
        )
        if fetched:
            public_item = redact_siga_details_for_role(dict(item), None)
            verification_event = build_verification_updated_event(public_item, source="siga_refresh")
            if verification_event:
                await manager.send_to_all(verification_event)
            siga_event = build_siga_snapshot_updated_event(public_item, source="siga_refresh")
            if siga_event:
                await manager.send_to_all(
                    siga_event,
                    roles={"admin", "jefe_operativo", "sistemas"},
                )
        return item

    apply_siga_snapshot_to_panel_item(
        item,
        cached_siga if isinstance(cached_siga, dict) else None,
        cache_valid=is_cache_valid(cached_siga_row, session=session) if cached_siga_row else None,
    )
    item["siga_url"] = build_siga_url(item.get("no_cuenta"), folio)
    return redact_siga_details_for_role(item, getattr(user, "role", None))


@router.patch("/inconsistencias/{inconsistencia_id}/resolution")
async def update_inconsistencia_panel_resolution(
    inconsistencia_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)

    payload = await request.json()
    if "resolved_by_panel" not in payload or not isinstance(payload["resolved_by_panel"], bool):
        raise HTTPException(400, "resolved_by_panel booleano requerido")

    ui_id = payload.get("ui_id")
    panel_resolved = bool(payload["resolved_by_panel"])
    existing_inc = (
        restrict_to_assigned(db.query(Inconsistencias), user, db)
        .filter(Inconsistencias.id == inconsistencia_id)
        .first()
    )
    if not existing_inc:
        raise HTTPException(404, "Inconsistencia no encontrada")
    was_open = bool(
        existing_inc
        and str(existing_inc.estatus or "").upper() == "ABIERTA"
    )

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

    if inc.session_id:
        session = (
            scoped_session_query(db, user)
            .filter(ChatSessions.id == inc.session_id)
            .first()
        )
        if session:
            verification_snapshot = build_verification_snapshot(db, session)
            if verification_snapshot:
                public_snapshot = redact_siga_details_for_role(dict(verification_snapshot), None)
                await manager.send_to_all({
                    "type": "verification_update",
                    "payload": minimal_verification_payload(public_snapshot),
                })
                verification_event = build_verification_updated_event(public_snapshot, source="panel")
                if verification_event:
                    await manager.send_to_all(verification_event)

            inconsistency_payload = {
                "id": inc.id,
                "ui_id": ui_id,
                "session_id": inc.session_id,
                "resolved_by_panel": panel_resolved,
                "resolved_by_siga": bool(inc.resolved_by_siga),
                "status": inc.estatus,
            }
            await manager.send_to_all({
                "type": "inconsistencia_updated",
                "payload": inconsistency_payload,
            })
            await manager.send_to_all(
                build_inconsistency_updated_event(
                    inc,
                    source="panel",
                    payload=inconsistency_payload,
                )
            )

    if issues_open_delta:
        await manager.send_to_all({
            "type": "dashboard_update",
            "session_id": inc.session_id,
            "payload": {
                "issues_open_delta": issues_open_delta,
                "session_id": inc.session_id,
            },
        })

    return {
        "id": inc.id,
        "ui_id": ui_id,
        "session_id": inc.session_id,
        "resolved_by_panel": panel_resolved,
        "resolved_by_siga": bool(inc.resolved_by_siga),
        "verification": verification_snapshot,
    }
# =========================================
# Obtener conversaciones (PAGINADO + DTO)
# =========================================
@router.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    limit: int = 10000,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
    # _: str = Depends(verify_api_key)
):
    if limit > 500:
        limit = 500

    sessions_query = restrict_to_assigned(db.query(ChatSessions), user, db)
    
    # 🕵️ Filtrar asesores para que no aparezcan en el panel de clientes
    if settings.ADVISOR_PHONES:
        sessions_query = sessions_query.filter(ChatSessions.phone.notin_(settings.ADVISOR_PHONES))

    sessions = (
        sessions_query
        .order_by(desc(ChatSessions.last_message_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    # teléfonos normalizados de sesiones
    normalized_phones = list({
        normalize_conversation_phone(s.phone)
        for s in sessions
        if s.phone
    })

    # QUERY MASIVA
    ventas = (
        db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == user.empresa_id
        )
        .all()
    )

    folios = [str(s.folio) for s in sessions if s.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    phone_to_name = {}

    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_conversation_phone(v.tel_1)
        if db_phone and v.nombre_completo:
            phone_to_name[db_phone] = v.nombre_completo.strip()

    grouped_sessions: dict[str, dict] = {}
    for s in sessions:
        phone_key = normalize_conversation_phone(s.phone) or str(s.phone or s.id)
        folio = str(s.folio) if s.folio else None
        cached_siga = get_cached_verification(s, folio, allow_stale=True) if folio else None
        no_cuenta = folio_to_no_cuenta.get(folio) if folio else None
        bridge_name = bridge_customer_name_from_snapshot(cached_siga)
        if not no_cuenta and isinstance(cached_siga, dict) and cached_siga.get("no_cuenta"):
            no_cuenta = str(cached_siga["no_cuenta"])

        group = grouped_sessions.get(phone_key)
        if not group:
            group = {
                "latest": s,
                "cuentas": [],
                "folios": [],
                "unread_count": 0,
                "last_customer_message_at": None,
                "bridge_name": None,
            }
            grouped_sessions[phone_key] = group

        group["unread_count"] += int(s.unread_count or 0)
        append_unique_text(group["cuentas"], no_cuenta)
        append_unique_text(group["folios"], folio)
        if bridge_name and not group.get("bridge_name"):
            group["bridge_name"] = bridge_name

        last_customer_at = group["last_customer_message_at"]
        if s.last_customer_message_at and (
            last_customer_at is None or s.last_customer_message_at > last_customer_at
        ):
            group["last_customer_message_at"] = s.last_customer_message_at

    response = []
    for phone_key, group in grouped_sessions.items():
        s = group["latest"]
        folio = str(s.folio) if s.folio else None
        cuentas = list(reversed(group["cuentas"]))
        folios_grupo = list(reversed(group["folios"]))

        response.append(
            ConversationResponse(
                id=s.id,
                phone=s.phone,
                name=phone_to_name.get(phone_key) or group.get("bridge_name"),
                last_message=s.last_message,
                last_message_at=s.last_message_at,
                unread_count=group["unread_count"],
                no_cuenta=", ".join(cuentas) if cuentas else None,
                folio=folio,
                folios=folios_grupo,
                status=classify_panel_status(
                    verification_data={"is_completed": False},
                    has_open_inconsistencia=False,
                    last_activity=s.last_message_at,
                    session_state=str(s.state or ""),
                    previous_state=str(s.previous_state or ""),
                ),
                last_customer_message_at=group["last_customer_message_at"],
            )
        )

    return response


@router.get("/conversations/{session_id}", response_model=ConversationResponse)
def get_conversation(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)

    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada",
    )

    phone_key = normalize_conversation_phone(session.phone)
    name = None
    if phone_key:
        venta = (
            db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo)
            .filter(
                func.right(BitacoraVentas.tel_1, 10) == phone_key,
                BitacoraVentas.id_emp_bv == user.empresa_id,
            )
            .order_by(desc(BitacoraVentas.id_venta_b))
            .first()
        )
        if venta and venta.nombre_completo:
            name = venta.nombre_completo.strip()

    folio = str(session.folio) if session.folio else None
    no_cuenta = None
    if folio:
        no_cuenta = resolve_cuentas_from_folios([folio], db, user).get(folio)
        cached_siga = get_cached_verification(session, folio, allow_stale=True)
        if not no_cuenta and isinstance(cached_siga, dict) and cached_siga.get("no_cuenta"):
            no_cuenta = str(cached_siga["no_cuenta"])
        name = name or bridge_customer_name_from_snapshot(cached_siga)

    return ConversationResponse(
        id=session.id,
        phone=session.phone,
        name=name,
        last_message=session.last_message,
        last_message_at=session.last_message_at,
        unread_count=int(session.unread_count or 0),
        no_cuenta=no_cuenta,
        folio=folio,
        folios=[folio] if folio else [],
        status=classify_panel_status(
            verification_data={"is_completed": False},
            has_open_inconsistencia=False,
            last_activity=session.last_message_at,
            session_state=str(session.state or ""),
            previous_state=str(session.previous_state or ""),
        ),
        last_customer_message_at=session.last_customer_message_at,
    )


# =========================================
# Obtener mensajes (PAGINADO REAL)
# =========================================
@router.get("/messages/{session_id}", response_model=PaginatedMessagesResponse)
def get_messages(
    session_id: int,
    limit: int = 10000,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),

    # _: str = Depends(verify_api_key)
):
    MAX_MESSAGES = 250
    limit = min(limit, MAX_MESSAGES)

    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="La sesion no existe",
    )

    if not session:
        raise HTTPException(404, "La sesión no existe")
    # evita acceso cruzado
    require_company_scope(user)

    phone_key = normalize_conversation_phone(session.phone)
    session_ids = [session_id]

    if phone_key:
        scoped_sessions = restrict_to_assigned(
            db.query(ChatSessions.id, ChatSessions.phone),
            user,
            db,
        ).all()
        session_ids = [
            row.id
            for row in scoped_sessions
            if normalize_conversation_phone(row.phone) == phone_key
        ] or [session_id]

    base_query = db.query(Message).filter(
        Message.session_id.in_(session_ids)
    )

    total = base_query.count()

    messages = (
        base_query
        .order_by(desc(Message.created_at), desc(Message.id))
        .offset(offset)
        .limit(limit)
        .all()
    )
    messages.reverse()
    attach_reactions_to_messages(db, messages)

    return PaginatedMessagesResponse(
        data=[
            MessageResponse(
                id=m.id,
                direction=m.direction,
                content=m.content,
                created_at=m.created_at,
                type=m.type,
                media_url=m.media_url,
                file_name=m.file_name,
                extra_json=m.extra_json,
                reactions=getattr(m, "reactions_payload", []),
            )
            for m in messages
        ],
        total=total,
        has_more=(offset + len(messages)) < total
    )




# =========================================
# Enviar mensaje desde panel (SEGURO + CONSISTENTE)
# =========================================
@router.post("/messages")
async def send_agent_message(
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "Mensaje vacío")

    if len(content) > 1000:
        raise HTTPException(400, "Mensaje demasiado largo")

    require_company_scope(user)
    require_reply_permission(user)

    session = get_scoped_session_or_404(
        db,
        user,
        payload.session_id,
        detail="Sesion no encontrada",
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    # 🛡️ VALIDACION: Ventana de 24 horas
    if session.last_customer_message_at and session.last_customer_message_at < mexico_now_naive() - timedelta(days=1):
        raise HTTPException(
            status_code=403,
            detail="La ventana de atención de 24 horas ha expirado. Por favor, contacte al cliente por llamada."
        )

    phone = session.phone
    was_active = bool(
        session.last_message_at
        and session.last_message_at >= mexico_now_naive() - timedelta(days=1)
    )

    try:
        response = await send_whatsapp_message(phone, content)
        provider_message_id = _extract_meta_message_id(response)

        now = mexico_now_naive()
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
            message_id=provider_message_id,
            created_at=now,
        )

        db.add(message)

        session.last_message_at = now
        session.last_message = content
        session.unread_count = 0

        db.flush()

        db.commit()

        await manager.send_to_all(build_new_message_event(session, message))

        await manager.send_to_all({
            "type": "dashboard_update",
            "payload": {
                "messages_in_delta": 0,
                "messages_out_delta": 1,
                "active_sessions_delta": 0 if was_active else 1,
                "session_id": session.id,
            },
        })

        await manager.send_to_all({
            "type": "verification_update",
            "payload": {
                "session_id": session.id,
                "last_activity": now.isoformat(),
            }
        })

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error enviando mensaje a WhatsApp"
        )

    return {"status": "sent"}
@router.post("/messages/file")
async def send_agent_file(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_panel_user),
):
    payload = await request.json()

    session_id = payload.get("session_id")
    media_url = payload.get("media_url")
    file_name = payload.get("file_name")
    media_type = payload.get("type")

    if not session_id or not media_url or not media_type:
        raise HTTPException(400, "Datos incompletos")

    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "session_id invalido")

    require_company_scope(user)
    require_reply_permission(user)

    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada",
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    # 🛡️ VALIDACION: Ventana de 24 horas
    if session.last_customer_message_at and session.last_customer_message_at < mexico_now_naive() - timedelta(days=1):
        raise HTTPException(
            status_code=403,
            detail="La ventana de atención de 24 horas ha expirado. Por favor, contacte al cliente por llamada."
        )

    phone = session.phone
    was_active = bool(
        session.last_message_at
        and session.last_message_at >= mexico_now_naive() - timedelta(days=1)
    )

    # =========================
    # 💾 1. GUARDAR PRIMERO
    # =========================
    content = payload.get("content")

    # 🚫 NO generar [MEDIA]
    if not content or content == "[MEDIA]":
        content = " "

    last_message = content.strip() if content and content.strip() else "Archivo adjunto"
    now = mexico_now_naive()

    try:
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
            type=media_type,
            media_url=media_url,
            file_name=file_name,
            extra_json=build_outgoing_media_metadata(
                source=media_url,
                caption=content,
                media_type=media_type,
            ),
            created_at=now,
        )

        db.add(message)
        session.last_message = last_message
        session.last_message_at = now
        session.unread_count = 0

        db.commit()
        db.refresh(message)

    except Exception:
        db.rollback()
        logger.exception("panel_agent_file_save_failed", extra={"session_id": session_id})
        raise HTTPException(500, "Error guardando mensaje")

    # =========================
    # 📡 2. WEBSOCKET (INMEDIATO)
    # =========================
    await manager.send_to_all(build_new_message_event(session, message))

    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "active_sessions_delta": 0 if was_active else 1,
            "session_id": session.id,
        },
    })

    snapshot = build_verification_snapshot(db, session)
    if snapshot:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": minimal_verification_payload(snapshot),
        })
        verification_event = build_verification_updated_event(snapshot, source="panel")
        if verification_event:
            await manager.send_to_all(verification_event)
    else:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": {
                "session_id": session.id,
                "last_activity": now.isoformat(),
            },
        })

    # =========================
    # 📤 3. WHATSAPP (ASYNC)
    # =========================
    async def send_media_safe():
        try:
            caption = message.content if message.content else None

            await send_whatsapp_media(
                phone=phone,
                media_url=media_url,
                media_type=media_type,
                caption=caption,
                filename=file_name
            )

        except Exception:
            logger.warning("panel_agent_file_whatsapp_send_failed", extra={"session_id": session.id})

    import asyncio
    asyncio.create_task(send_media_safe())

    return {"status": "sent"}

# =========================================
# Enviar plantilla de reactivación
# =========================================
from pydantic import BaseModel

class ReactivateRequest(BaseModel):
    template_key: str

@router.post("/conversations/{session_id}/reactivate")
async def reactivate_conversation(
    session_id: int,
    payload: ReactivateRequest,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    require_company_scope(user)

    chat = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada"
    )

    TEMPLATE_MAP = {
        "inactivity": ("reactivacion_inactividad", "👋🏻 Hola, notamos que tu proceso quedó en pausa.\n\n⏳ Toca el botón de abajo o responde este mensaje para retomar tu verificación y asegurar tus beneficios."),
        "advisor": ("reactivacion_asesor", "👋🏻 Hola, un asesor ha revisado tu caso y está listo para ayudarte.\n\n🧑🏻‍💻 Por favor, toca el botón de abajo para que podamos brindarte atención personalizada."),
        "data_ready": ("reactivacion_datos_listos", "👋🏻 Hola, te informamos que los datos de tu compra ya están registrados en nuestro sistema.\n\n✅ Toca el botón de abajo para iniciar tu proceso de verificación."),
        "collections": ("reactivacion_cobranza", "👋🏻 Hola, nos ponemos en contacto contigo para darle seguimiento al estado de tu cuenta.\n\n🤝🏻 Si tienes alguna duda con tus pagos o necesitas asistencia, toca el botón de abajo para que un asesor te atienda personalmente."),
    }

    if payload.template_key not in TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Plantilla no válida")

    template_name, text_content = TEMPLATE_MAP[payload.template_key]

    from app.adapters.whatsapp_client import send_template_message, _extract_meta_message_id
    from app.services.message_service import save_message
    from app.utils.timezone import mexico_now_naive
    from app.services.ws_events import build_new_message_event

    response = await send_template_message(
        phone=chat.phone,
        template_name=template_name
    )
    
    if not response or response.status_code >= 400:
        error_msg = "Error desconocido de Meta"
        if response:
            try:
                error_msg = response.json().get("error", {}).get("message", error_msg)
            except:
                error_msg = response.text
        raise HTTPException(status_code=400, detail=f"No se pudo enviar la plantilla a Meta: {error_msg}")
        
    provider_message_id = _extract_meta_message_id(response)

    msg = save_message(
        db=db,
        session_id=session_id,
        phone=chat.phone,
        direction="agent",
        content=text_content,
        message_id=provider_message_id,
    )
    msg.type = "template"

    now = mexico_now_naive()
    chat.last_message = "Plantilla enviada"
    chat.last_message_at = now
    chat.unread_count = 0
    if payload.template_key == "collections":
        chat.status = "COBRANZA"

    db.commit()
    db.refresh(msg)

    from app.websockets.manager import manager
    await manager.send_to_all(build_new_message_event(chat, msg))
    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "session_id": chat.id,
        },
    })

    return {"status": "sent"}

# =========================================
# Retomar control del chatbot
# =========================================
@router.post("/conversations/{session_id}/resume-bot")
async def resume_bot_control(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    require_company_scope(user)
    
    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada"
    )

    from app.utils.timezone import mexico_now_naive
    from datetime import timedelta

    # 🛡️ VALIDACION: Ventana de 24 horas expirada
    if session.last_customer_message_at and session.last_customer_message_at < mexico_now_naive() - timedelta(days=1):
        raise HTTPException(
            status_code=400,
            detail="No es posible que el chatbot tome el control porque la ventana de atención de 24 horas cerró."
        )

    from app.core.states.states import ChatState

    # 🗺️ Mapeo de descripciones legibles para el asesor
    STATE_DESCRIPTIONS = {
        ChatState.INICIO.value: "Confirmación de nombre (Inicio)",
        ChatState.INICIO2.value: "Confirmación de nombre",
        ChatState.CONFIRMAR_NOMBRE.value: "Confirmación de nombre",
        ChatState.CONFIRMAR_DOMICILIO.value: "Confirmación de domicilio",
        ChatState.CONFIRMAR_FECHA.value: "Confirmación de fecha de venta",
        ChatState.CONFIRMAR_PRODUCTO.value: "Confirmación de producto",
        ChatState.CONFIRMAR_ESTADO_PRODUCTO.value: "Confirmación de estado del producto",
        ChatState.CONFIRMAR_COMPONENTES.value: "Confirmación de componentes recibidos",
        ChatState.CONFIRMAR_PAGO_INICIAL.value: "Confirmación de pago inicial",
        ChatState.INFO_PAGOS.value: "Información de pagos",
        ChatState.INFO_METODOS_PAGO.value: "Información de métodos de pago",
        ChatState.INFO_PLAN_3_MESES.value: "Información de plan de 3 meses",
        ChatState.INFO_OTROS_PLANES.value: "Información de otros planes",
        ChatState.INFO_BENEFICIOS.value: "Información de beneficios",
        ChatState.INFO_BENEFICIOS2.value: "Información de beneficios",
        ChatState.FINALIZADO.value: "Verificación finalizada con éxito",
        ChatState.ESPERANDO_REGISTRO.value: "Espera de registro de venta",
        ChatState.RECORDATORIO.value: "Recordatorio automático por inactividad",
        ChatState.RECORDATORIO_1H.value: "Recordatorio automático (1 hora)",
        ChatState.RECORDATORIO_2H.value: "Recordatorio automático (2 horas)",
        ChatState.RECORDATORIO_24H.value: "Recordatorio automático (24 horas)",
        ChatState.ESPERA.value: "Espera de folio por parte del cliente",
        ChatState.MENU_AYUDA.value: "Menú de ayuda inicial",
        ChatState.FUERA_DE_FLUJO.value: "Resolución de dudas generales",
        ChatState.COMPONENTES_FALTANTES.value: "Registro de componentes faltantes",
        ChatState.COMPONENTES_CONFIRMAR_FALTANTES.value: "Confirmación de lista de faltantes",
        ChatState.VERIFICAR_FOTO_COMPONENTE.value: "Verificación de fotos de componentes",
        ChatState.INCONSISTENCIA.value: "Registro de inconsistencia en datos",
    }

    state_friendly = STATE_DESCRIPTIONS.get(session.state, session.state)
    
    if session.state not in (ChatState.ACLARACION.value, ChatState.LLAMADA.value):
        raise HTTPException(400, f"El chatbot ya tiene el control de la conversación (Etapa actual: {state_friendly})")

    # ——————————————————————————————————————————————————————————————
    # Determinar el estado correcto al que volver
    # ——————————————————————————————————————————————————————————————
    # Si veníamos de LLAMADA, su previous_state puede ser ACLARACION (o un RECORDATORIO),
    # lo cual no es el punto real del flujo. Buscamos el estado real de verificación
    # que antecedía a toda la cadena de interrupciones.
    current_state_value = session.state
    
    from app.core.states.state_types import get_state_type
    from app.core.flow.flow import NEXT_STATE_MAP
    from app.core.states.state_renderer import render_state
    from app.content import messages as msg
    
    # Resolver la cadena de previous_state hasta encontrar un estado de flujo real
    def resolve_real_previous_state(session_obj, db_session) -> "ChatState":
        """
        Encuentra el último estado real de verificación (confirmación o información)
        ignorando interrupciones (ACLARACION, LLAMADA, RECORDATORIO, etc.).
        Usa FlowEvents como respaldo si previous_state apunta a una interrupción.
        """
        INTERRUPTION_STATE_VALUES = {
            ChatState.ACLARACION.value,
            ChatState.LLAMADA.value,
            ChatState.FUERA_DE_FLUJO.value,
            ChatState.DUDA.value,
            ChatState.MENU_DUDA.value,
            ChatState.MENU_AYUDA.value,
            ChatState.RECORDATORIO.value,
            ChatState.RECORDATORIO_1H.value,
            ChatState.RECORDATORIO_2H.value,
            ChatState.RECORDATORIO_24H.value,
        }
        
        # 1. Intentar con previous_state directo
        candidate = session_obj.previous_state
        if candidate and candidate not in INTERRUPTION_STATE_VALUES:
            try:
                return ChatState(candidate)
            except ValueError:
                pass
        
        # 2. Respaldo: buscar el último to_state de flujo real en FlowEvents
        flow_rows = (
            db_session.query(FlowEvent.to_state)
            .filter(
                FlowEvent.session_id == session_obj.id,
                FlowEvent.to_state.notin_(list(INTERRUPTION_STATE_VALUES) + [None]),
            )
            .order_by(FlowEvent.id.desc())
            .limit(10)
            .all()
        )
        
        for (to_state_val,) in flow_rows:
            try:
                return ChatState(to_state_val)
            except ValueError:
                continue
        
        return ChatState.INICIO
    
    prev_state_enum = resolve_real_previous_state(session, db)
    
    # 1. Si no hay folio, pedimos el folio.
    if not session.folio:
        next_state = ChatState.CAMBIAR_FOLIO
        reply_text, botones, image_id = render_state(next_state, session, db)
        reply_text = msg.PEDIR_FOLIO_REANUDAR
    else:
        # 2. Si era pregunta de confirmación, saltamos a la siguiente. Si es información, la repetimos.
        if prev_state_enum and get_state_type(prev_state_enum) == "confirmation":
            next_state = NEXT_STATE_MAP.get(prev_state_enum) or prev_state_enum or ChatState.INICIO
        else:
            next_state = prev_state_enum or ChatState.INICIO
            
        reply_text, botones, image_id = render_state(next_state, session, db)
        
        # Agregar etiqueta de continuación si no es el mensaje de inicio
        if next_state != ChatState.INICIO and next_state != ChatState.INICIO2:
            reply_text = f"{msg.CONTINUAR_VERIFICACION}\n\n{reply_text}"
    
    # Guardar estado y mensaje en DB
    session.state = next_state.value
    
    from app.services.message_service import save_message
    from app.utils.timezone import mexico_now_naive
    
    flow_media_type = "video" if str(image_id or "").lower().endswith(".mp4") else "image" if image_id else None
    media_metadata = build_outgoing_media_metadata(
        source=image_id,
        caption=reply_text,
        media_type=flow_media_type,
    )
    media = media_metadata.get("media") if isinstance(media_metadata, dict) else None
    bot_msg = save_message(
        db=db,
        session_id=session.id,
        phone=session.phone,
        direction="out",
        content=reply_text,
        type=str(media.get("type") or "text") if isinstance(media, dict) else "text",
        media_url=media.get("url") if isinstance(media, dict) else None,
        extra_json=merge_message_metadata(
            build_outgoing_interactive_metadata(reply_text, botones),
            media_metadata,
        ),
    )
    
    session.last_message = "Retomó el chatbot"
    session.last_message_at = mexico_now_naive()
    
    # Solo cerrar inconsistencias abiertas cuando venimos de ACLARACION,
    # no de LLAMADA (donde el problema era de comunicación, no de datos incorrectos).
    if current_state_value == ChatState.ACLARACION.value:
        from sqlalchemy import func
        from app.db.models import Inconsistencias
        
        open_incs = db.query(Inconsistencias).filter(
            Inconsistencias.session_id == session.id,
            func.upper(Inconsistencias.estatus) == "ABIERTA"
        ).all()
        
        for inc in open_incs:
            inc.estatus = "RESUELTA"
            inc.resolved_by_panel = True
    
    db.commit()
    db.refresh(session)
    db.refresh(bot_msg)
    
    # Enviar WhatsApp
    from app.adapters.whatsapp_client import send_whatsapp_message
    response = await send_whatsapp_message(
        phone=session.phone,
        text=reply_text,
        buttons=botones,
        image_id=image_id
    )
    provider_message_id = _extract_meta_message_id(response)
    if provider_message_id and not bot_msg.message_id:
        bot_msg.message_id = provider_message_id
        db.commit()
        db.refresh(bot_msg)
    
    # Broadcast Panel
    from app.websockets.manager import manager
    
    await manager.send_to_all(build_new_message_event(session, bot_msg))
    
    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "active_sessions_delta": 0,
            "session_id": session.id,
        },
    })
    
    from app.services.verification_panel_service import build_verification_snapshot
    snapshot = build_verification_snapshot(db, session)
    if snapshot:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": minimal_verification_payload(snapshot),
        })
        verification_event = build_verification_updated_event(snapshot, source="panel")
        if verification_event:
            await manager.send_to_all(verification_event)
        
    return {"status": "success", "message": "El chatbot ha retomado el control", "next_state": next_state.value}

# =========================================
# Verificacion Manual por Llamada (Asesor)
# =========================================
@router.post("/conversations/{session_id}/verify-by-call")
async def verify_by_call(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    require_company_scope(user)
    
    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada"
    )

    from app.core.states.states import ChatState
    from app.utils.timezone import mexico_now_naive
    from sqlalchemy import func
    from app.db.models import Inconsistencias, VerificacionCuenta
    from app.services.reminder_service import cancel_pending_inactivity_reminders
    from app.services.verification_service import VerificationService, log_flow_event
    from app.core.verification.verification_schema import VERIFICATION_STEP_ORDER
    from app.services.verification_panel_service import build_verification_snapshot
    from app.websockets.manager import manager

    if session.state not in (ChatState.LLAMADA.value, ChatState.ACLARACION.value):
        pass # Permitimos la verificacion manual en estados inactivos si el asesor lo requiere.

    # 1. Registrar transicion de estado en FlowEvent
    log_flow_event(
        db=db,
        session=session,
        from_state=session.state,
        to_state=ChatState.FINALIZADO.value,
        trigger_text="Verificación manual por llamada por el asesor",
        event_type="panel_action"
    )

    # 2. Actualizar ChatSessions a FINALIZADO
    session.previous_state = session.state
    session.state = ChatState.FINALIZADO.value
    session.updated_at = mexico_now_naive()

    # 3. Cancelar los recordatorios pendientes de inactividad
    if session.phone:
        cancel_pending_inactivity_reminders(db, session.phone)

    # 4. Actualizar VerificacionCuenta (13 pasos en 1)
    if session.folio:
        service = VerificationService(db)
        no_cuenta = service.resolve_no_cuenta_from_folio(str(session.folio), user.empresa_id)
        if no_cuenta:
            verification = (
                db.query(VerificacionCuenta)
                .filter(VerificacionCuenta.no_cuenta == no_cuenta)
                .first()
            )
            if not verification:
                verification = VerificacionCuenta(
                    no_cuenta=no_cuenta,
                    json={},
                    version=0
                )
                db.add(verification)
                db.flush()
            
            verification.json = {k: 1 for k in VERIFICATION_STEP_ORDER}
            verification.version += 1

            # 5. Cerrar inconsistencias asociadas a este folio
            open_incs = db.query(Inconsistencias).filter(
                Inconsistencias.folio == session.folio,
                func.upper(Inconsistencias.estatus) == "ABIERTA"
            ).all()
            for inc in open_incs:
                inc.estatus = "RESUELTA"
                inc.resolved_by_panel = True

    db.commit()
    db.refresh(session)

    # 6. Broadcast via WebSockets para actualizar el UI sin recargar
    snapshot = build_verification_snapshot(db, session)
    if snapshot:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": minimal_verification_payload(snapshot),
        })
        
        from app.router.panel_router import redact_siga_details_for_role
        public_snapshot = redact_siga_details_for_role(dict(snapshot), None)
        verification_event = build_verification_updated_event(public_snapshot, source="panel")
        if verification_event:
            await manager.send_to_all(verification_event)

    return {"status": "success", "message": "Verificado exitosamente por llamada"}

