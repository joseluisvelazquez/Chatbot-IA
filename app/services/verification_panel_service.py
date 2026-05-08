from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.core.states.states import ChatState
from app.core.verification_steps import STEP_ORDER
from app.core.verification.verification_schema import normalize_progress_payload
from app.siga.siga_repository import obtener_venta_por_folio
from app.services.verification_service import VerificationService
from app.services.verification_tracker import STEP_MAP
from app.services.siga_navigation import build_siga_account_url
from app.services.siga_bridge_cache import (
    apply_siga_snapshot_to_panel_item,
    get_cached_verification,
    get_cached_verification_row,
    is_cache_valid,
)
from app.db.models import ChatSessions, FlowEvent, VerificacionCuenta, Inconsistencias
from app.utils.inconsistencias_serializer import (
    serialize_inconsistencias,
    summarize_inconsistencias,
)
from app.utils.timezone import mexico_now_naive

INACTIVITY_MINUTES = 30

PANEL_STEP_MAP = {
    **STEP_MAP,
    ChatState.COMPONENTES_FALTANTES: "componentes",
    ChatState.VERIFICAR_FOTO_COMPONENTE: "componentes",
    ChatState.COMPONENTES_CONFIRMAR_FALTANTES: "componentes",
    ChatState.FINALIZADO: "finalizado",
}

INTERRUPTION_STATES = {
    ChatState.INCONSISTENCIA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.DUDA,
    ChatState.MENU_DUDA,
    ChatState.MENU_AYUDA,
    ChatState.ACLARACION,
    ChatState.LLAMADA,
    ChatState.RECORDATORIO,
    ChatState.RECORDATORIO_1H,
    ChatState.RECORDATORIO_2H,
}


def _coerce_chat_state(value: Any) -> Optional[ChatState]:
    if isinstance(value, ChatState):
        return value

    if not value:
        return None

    try:
        return ChatState(str(value))
    except ValueError:
        return None


def _step_from_state(value: Any) -> Optional[str]:
    state = _coerce_chat_state(value)
    if not state:
        return None

    return PANEL_STEP_MAP.get(state)


def resolve_panel_current_step(
    session: ChatSessions,
    fallback_step: Optional[str] = None,
) -> str:
    current_state = _coerce_chat_state(getattr(session, "state", None))

    if current_state == ChatState.FINALIZADO:
        return "finalizado"

    current_step = _step_from_state(current_state)
    if current_step:
        return current_step

    if current_state in INTERRUPTION_STATES:
        previous_step = _step_from_state(getattr(session, "previous_state", None))
        if previous_step:
            return previous_step

    return fallback_step or "inicio"


def build_verification_snapshot(
    db: Session,
    session: ChatSessions,
) -> Optional[dict]:
    service = VerificationService(db)
    folio = str(session.folio) if session.folio else ""
    cached_siga = get_cached_verification(session, folio, allow_stale=True) if folio else None
    cached_row = get_cached_verification_row(session, folio, allow_stale=True) if folio else None

    no_cuenta = (
        service.resolve_no_cuenta_from_folio(folio)
        if folio
        else None
    )
    if not no_cuenta and cached_siga:
        no_cuenta = cached_siga.get("no_cuenta")

    if not no_cuenta and not cached_siga:
        return None

    verif = None
    if no_cuenta:
        verif = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .first()
        )

    if not verif and not cached_siga:
        return None

    progress_json = merge_progress_from_flow_events(
        db,
        session.id,
        verif.json if verif and isinstance(verif.json, dict) else {},
        current_state=session.state,
    )
    verification_data = compute_verification(progress_json)

    inconsistencias = (
        db.query(Inconsistencias)
            .filter(Inconsistencias.folio == folio)
            .all()
    )

    serialized_inconsistencias = serialize_inconsistencias(inconsistencias)
    open_inconsistencia = has_open_inconsistencia(serialized_inconsistencias)
    inconsistencia_summary = summarize_inconsistencias(serialized_inconsistencias)

    status = classify_panel_status(
        verification_data=verification_data,
        has_open_inconsistencia=open_inconsistencia,
        last_activity=session.last_message_at,
        requires_human=False,
    )

    item = {
        "session_id": session.id,
        "folio": folio,
        "phone": session.phone,
        "no_cuenta": no_cuenta,
        "siga_url": build_siga_account_url(no_cuenta, folio),
        "status": status,
        "progress_pct": verification_data["progress_pct"],
        "current_step": resolve_panel_current_step(
            session,
            verification_data["current_step"],
        ),
        "inconsistencias": serialized_inconsistencias,
        "inconsistencias_count": inconsistencia_summary["severity_counts"]["total"],
        "severity_counts": inconsistencia_summary["severity_counts"],
        "highest_severity": inconsistencia_summary["highest_severity"],
        "confirmed_count": verification_data["progress_count"],
        "total_steps": verification_data["total_steps"],
        "last_activity": session.last_message_at.isoformat()
        if session.last_message_at
        else "",
    }
    return apply_siga_snapshot_to_panel_item(
        item,
        cached_siga,
        cache_valid=is_cache_valid(cached_row, session=session) if cached_row else None,
    )


def merge_progress_from_flow_events(
    db: Session,
    session_id: int,
    progress: Optional[Dict[str, int]],
    current_state: Any = None,
) -> Dict[str, int]:
    normalized = normalize_progress_payload(progress or {})

    rows = (
        db.query(FlowEvent.to_state)
        .filter(
            FlowEvent.session_id == session_id,
            FlowEvent.to_state.isnot(None),
        )
        .order_by(FlowEvent.id.asc())
        .all()
    )

    for (to_state,) in rows:
        step = _step_from_state(to_state)
        if step not in STEP_ORDER:
            continue

        max_index = STEP_ORDER.index(step)
        for reached_step in STEP_ORDER[: max_index + 1]:
            if normalized.get(reached_step, 0) == 0:
                normalized[reached_step] = 1

    if _coerce_chat_state(current_state) == ChatState.FINALIZADO:
        for step in STEP_ORDER:
            if normalized.get(step, 0) == 0:
                normalized[step] = 1

    return normalized


def compute_verification(progress: Optional[Dict[str, int]]) -> Dict[str, Any]:
    normalized = normalize_progress_payload(progress or {})

    steps = STEP_ORDER
    total_steps = len(steps)

    progressed_steps = [
        step for step in steps if normalized.get(step) in (1, 2)
    ]
    progress_count = len(progressed_steps)
    progress_pct = int((progress_count / total_steps) * 100) if total_steps else 0

    last_step = None
    for step in steps:
        if normalized.get(step) in (1, 2):
            last_step = step

    if not last_step:
        last_step = "inicio"

    inconsistent_steps = [
        step for step in steps if normalized.get(step) == 2
    ]

    is_completed = (
        normalized.get("beneficios") in (1, 2)
        or normalized.get("finalizado") == 1
    )
    if is_completed:
        progress_count = total_steps
        progress_pct = 100 if total_steps else 0
        last_step = "finalizado"

    return {
        "progress_pct": progress_pct,
        "current_step": last_step,
        "inconsistencies": inconsistent_steps,
        "progress_count": progress_count,
        "total_steps": total_steps,
        "normalized_progress": normalized,
        "is_completed": is_completed,
    }

def classify_panel_status(
    verification_data: Dict[str, Any],
    has_open_inconsistencia: bool,
    last_activity: Optional[datetime],
    requires_human: bool = False,
) -> str:

    # 🔴 PRIORIDAD 1: asesor
    if requires_human:
        return "human_required"

    if has_open_inconsistencia:
        return "inconsistent"

    # 🟢 completado
    if verification_data.get("is_completed",False):
        return "completed"

    # 🟠 inconsistencias
    if has_open_inconsistencia:
        return "inconsistent"

    # 🟡 inactivo
    if last_activity is not None:
        now = mexico_now_naive()
        if now - last_activity > timedelta(minutes=INACTIVITY_MINUTES):
            return "stalled"

    # 🔵 normal
    return "in_progress"

def resolve_no_cuenta(
    db: Session,
    folio: str,
    company_id: int = 1,
) -> Optional[str]:
    if not folio:
        return None

    venta = obtener_venta_por_folio(db, str(folio), company_id)
    if not venta:
        return None

    no_cuenta = getattr(venta, "no_cuenta", None)
    if not no_cuenta:
        return None

    return str(no_cuenta)


def resolve_cuentas_from_folios(
    folios: Iterable[str],
    db: Optional[Session] = None,
    company_id: int = 1,
) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}

    for folio in folios:
        folio_key = str(folio)
        if db is None:
            result[folio_key] = None
            continue

        try:
            result[folio_key] = resolve_no_cuenta(db, folio_key, company_id)
        except Exception:
            result[folio_key] = None

    return result


def group_inconsistencias_by_folio(inconsistencias: Iterable[Any]) -> Dict[str, list[Any]]:
    grouped: Dict[str, list[Any]] = defaultdict(list)

    for item in inconsistencias:
        folio = getattr(item, "folio", None)
        if folio:
            grouped[str(folio)].append(item)

    return grouped

def has_open_inconsistencia(items: list[Any]) -> bool:
    if not items:
        return False

    for item in items:
        if isinstance(item, dict):
            if (item.get("estado") or "").upper() == "ABIERTA":
                return True
            continue

        estatus = getattr(item, "estatus", None)
        if isinstance(estatus, str) and estatus.upper() == "ABIERTA":
            return True

        activa = getattr(item, "activa", None)
        if activa is True:
            return True

    return False
