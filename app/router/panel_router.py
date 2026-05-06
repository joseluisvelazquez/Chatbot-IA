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

from app.adapters.whatsapp_client import send_whatsapp_message
from app.db.session import get_db
from app.security.auth_service import decode_panel_session, restrict_to_assigned
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
    resolve_panel_current_step,
)
from app.utils.timezone import mexico_now_naive
from app.services.inconsistencias_service import mark_panel_resolution
from app.services.siga_bridge_cache import (
    apply_siga_snapshot_to_panel_item,
    get_cached_verification,
    get_cached_verification_row,
    get_or_fetch_verification,
    is_cache_valid,
)
from app.services.siga_navigation import build_siga_account_url
from app.db.models import BitacoraVentas

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
    if role in ("admin", "jefe_operativo"):
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
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")


def require_reply_permission(user) -> None:
    if user.role not in ("admin", "ventas", "cobranza", "jefe_operativo", "sistemas"):
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
        await websocket.close(code=1008)
        return

    await websocket.accept()
    websocket.state.user = user
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
                await manager.send_to_all({
                    "type": "typing",
                    "session_id": payload.get("session_id")
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

    session.unread_count = 0
    db.commit()

    await manager.send_to_all({
        "type": "update_unread",
        "session_id": session.id,
        "unread_count": 0
    })

    return {"status": "ok"}

def resolve_cuentas_from_folios(folios: list[str], db: Session, user) -> dict:
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    unique_folios = [str(folio) for folio in dict.fromkeys(folios) if folio]
    result = {folio: None for folio in unique_folios}

    if not unique_folios:
        return result

    ventas = (
        db.query(BitacoraVentas.folio, BitacoraVentas.no_cuenta)
        .filter(
            BitacoraVentas.folio.in_(unique_folios),
            BitacoraVentas.id_emp_bv == 1,
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

    events = (
        db.query(
            FlowEvent.session_id,
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
    session_max_index: dict[int, int] = {}

    for e in events:
        step = STEP_MAP.get(e.to_state)

        if step not in step_index:
            continue

        current_index = step_index[step]
        previous_index = session_max_index.get(e.session_id, -1)
        if current_index > previous_index:
            session_max_index[e.session_id] = current_index

        # guardar primera vez que llegó al step

    sessions = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
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

    # --------------------------------------
    # CONTAR USUARIOS POR STEP
    # --------------------------------------
    step_counts = {step: 0 for step in FUNNEL_STEPS}

    for max_index in session_max_index.values():
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
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    valid_statuses = {
        None,
        "in_progress",
        "inconsistent",
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
        .order_by(ChatSessions.last_message_at.desc())
    )

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
    def normalize_phone(phone: str | None) -> str:
        if not phone:
            return ""
        phone = str(phone).replace("+", "").strip()
        if phone.startswith("52") and len(phone) > 10:
            phone = phone[2:]
        return phone[-10:]
    
    # =========================
    # 📞 RESOLVER NOMBRES (BATCH)
    # =========================
    normalized_phones = list({
        normalize_phone(s.phone)
        for s in sessions
        if s.phone
    })

    ventas = (
        restrict_to_assigned(db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo), user, db)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == 1
        )
        .all()
    )

    phone_to_name = {}
    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_phone(v.tel_1)
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
        progress = verification.json if verification else {}

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
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

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

    no_cuenta = service.resolve_no_cuenta_from_folio(str(session.folio)) if session.folio else None
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
        requires_human=False,
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
        "folio": folio,
        "name": (
            cached_siga.get("customer", {}).get("name")
            if isinstance(cached_siga, dict) and isinstance(cached_siga.get("customer"), dict)
            else None
        ),
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
    if user.role in ("admin", "jefe_operativo"):
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
                refreshed_data = compute_verification(refreshed_verification.json or {})
                item.update(
                    {
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
            await manager.send_to_all({
                "type": "verification_updated",
                "session_id": session.id,
                "folio": folio,
                "no_cuenta": item.get("no_cuenta"),
                "status": item.get("status"),
                "updated_at": item.get("last_activity"),
                "source": "siga_refresh",
                "payload": public_item,
            })
            await manager.send_to_all(
                {
                    "type": "siga_snapshot_updated",
                    "session_id": session.id,
                    "folio": folio,
                    "no_cuenta": item.get("no_cuenta"),
                    "status": item.get("status"),
                    "updated_at": (
                        item.get("siga", {}).get("fetched_at")
                        if isinstance(item.get("siga"), dict)
                        else None
                    ),
                    "source": "siga_refresh",
                    "payload": item,
                },
                roles={"admin", "jefe_operativo"},
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
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

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
                    "payload": public_snapshot,
                })
                await manager.send_to_all({
                    "type": "verification_updated",
                    "session_id": session.id,
                    "folio": public_snapshot.get("folio"),
                    "no_cuenta": public_snapshot.get("no_cuenta"),
                    "status": public_snapshot.get("status"),
                    "updated_at": public_snapshot.get("last_activity"),
                    "source": "panel",
                    "payload": public_snapshot,
                })

            inconsistency_payload = {
                "id": inc.id,
                "ui_id": ui_id,
                "session_id": inc.session_id,
                "resolved_by_panel": panel_resolved,
                "resolved_by_siga": bool(inc.resolved_by_siga),
            }
            await manager.send_to_all({
                "type": "inconsistencia_updated",
                "payload": inconsistency_payload,
            })
            await manager.send_to_all({
                "type": "inconsistency_updated",
                "session_id": inc.session_id,
                "source": "panel",
                "payload": inconsistency_payload,
            })

    if issues_open_delta:
        await manager.send_to_all({
            "type": "dashboard_update",
            "payload": {
                "issues_open_delta": issues_open_delta,
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

    sessions = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .order_by(desc(ChatSessions.last_message_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    def normalize_phone(phone: str | None) -> str:
        if not phone:
            return ""

        phone = str(phone).replace("+", "").strip()

        if phone.startswith("52") and len(phone) > 10:
            phone = phone[2:]

        return phone[-10:]
    
    # teléfonos normalizados de sesiones
    normalized_phones = list({
        normalize_phone(s.phone)
        for s in sessions
        if s.phone
    })

    # QUERY MASIVA
    ventas = (
        db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == 1
        )
        .all()
    )

    folios = [str(s.folio) for s in sessions if s.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    phone_to_name = {}

    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_phone(v.tel_1)
        if db_phone and v.nombre_completo:
            phone_to_name[db_phone] = v.nombre_completo.strip()

    response = []
    for s in sessions:
        folio = str(s.folio) if s.folio else None
        cached_siga = get_cached_verification(s, folio, allow_stale=True) if folio else None
        no_cuenta = folio_to_no_cuenta.get(folio) if folio else None
        if not no_cuenta and isinstance(cached_siga, dict) and cached_siga.get("no_cuenta"):
            no_cuenta = str(cached_siga["no_cuenta"])

        response.append(
            ConversationResponse(
                id=s.id,
                phone=s.phone,
                name=phone_to_name.get(normalize_phone(s.phone)),
                last_message=s.last_message,
                last_message_at=s.last_message_at,
                unread_count=s.unread_count,
                no_cuenta=no_cuenta,
                folio=folio,
            )
        )

    return response


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
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    base_query = db.query(Message).filter(
        Message.session_id == session_id
    )

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
                id=m.id,
                direction=m.direction,
                content=m.content,
                created_at=m.created_at,
                type=m.type,
                media_url=m.media_url,
                file_name=m.file_name
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

    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")
    require_reply_permission(user)

    session = get_scoped_session_or_404(
        db,
        user,
        payload.session_id,
        detail="Sesion no encontrada",
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    phone = session.phone
    was_active = bool(
        session.last_message_at
        and session.last_message_at >= mexico_now_naive() - timedelta(days=1)
    )

    try:
        await send_whatsapp_message(phone, content)

        now = mexico_now_naive()
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
            created_at=now,
        )

        db.add(message)

        session.last_message_at = now
        session.last_message = content

        db.flush()

        message_payload = {
            "id": message.id,
            "phone": phone,
            "content": message.content,
            "direction": message.direction,
            "created_at": message.created_at.isoformat() if message.created_at else now.isoformat()
        }

        db.commit()

        await manager.send_to_all({
            "type": "new_message",
            "session_id": session.id,
            "phone": session.phone,
            "conversation": {
                "id": session.id,
                "phone": session.phone,
                "name": None,
                "last_message": message.content,
                "last_message_at": message_payload["created_at"],
                "unread_count": 0,
                "folio": str(session.folio) if session.folio else None,
            },
            "message": message_payload
        })

        await manager.send_to_all({
            "type": "dashboard_update",
            "payload": {
                "messages_in_delta": 0,
                "messages_out_delta": 1,
                "active_sessions_delta": 0 if was_active else 1,
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

    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")
    require_reply_permission(user)

    session = get_scoped_session_or_404(
        db,
        user,
        session_id,
        detail="Sesion no encontrada",
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

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
    await manager.send_to_all({
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
        },
        "message": {
            "id": message.id,
            "phone": session.phone,
            "content": message.content,
            "direction": "agent",
            "type": media_type,
            "media_url": media_url,
            "file_name": file_name,
            "created_at": message.created_at.isoformat()
        },
        "unread_count": 0,
    })

    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "active_sessions_delta": 0 if was_active else 1,
        },
    })

    snapshot = build_verification_snapshot(db, session)
    if snapshot:
        await manager.send_to_all({
            "type": "verification_update",
            "payload": snapshot,
        })
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
