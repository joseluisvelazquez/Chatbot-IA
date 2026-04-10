from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.core.verification_steps import STEP_ORDER
from app.core.verification_schema import normalize_progress_payload
from app.siga.siga_repository import obtener_venta_por_folio
from app.services.verification_service import VerificationService
from app.db.models import ChatSessions, VerificacionCuenta, Inconsistencias
from app.utils.inconsistencias_serializer import serialize_inconsistencias

INACTIVITY_MINUTES = 30


def build_verification_snapshot(
    db: Session,
    session: ChatSessions,
) -> Optional[dict]:
    service = VerificationService(db)

    no_cuenta = (
        service.resolve_no_cuenta_from_folio(str(session.folio))
        if session.folio
        else None
    )

    if not no_cuenta:
        return None

    verif = (
        db.query(VerificacionCuenta)
        .filter(VerificacionCuenta.no_cuenta == no_cuenta)
        .first()
    )

    if not verif:
        return None

    progress_json = verif.json or {}
    verification_data = compute_verification(progress_json)

    inconsistencias = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.folio == str(session.folio))
        .all()
    )

    serialized_inconsistencias = serialize_inconsistencias(inconsistencias)
    open_inconsistencia = has_open_inconsistencia(serialized_inconsistencias)

    status = classify_panel_status(
        verification_data=verification_data,
        has_open_inconsistencia=open_inconsistencia,
        last_activity=session.last_message_at,
        requires_human=False,
    )

    return {
        "session_id": session.id,
        "folio": str(session.folio) if session.folio else "",
        "phone": session.phone,
        "no_cuenta": no_cuenta,
        "status": status,
        "progress_pct": verification_data["progress_pct"],
        "current_step": verification_data["current_step"],
        "inconsistencias": serialized_inconsistencias,
        "inconsistencias_count": len(serialized_inconsistencias),
        "last_activity": session.last_message_at.isoformat()
        if session.last_message_at
        else "",
    }
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

    # 🟢 completado
    if verification_data.get("is_completed",False):
        return "completed"

    # 🟠 inconsistencias
    if has_open_inconsistencia:
        return "inconsistent"

    # 🟡 inactivo
    if last_activity is not None:
        now = datetime.utcnow()
        if now - last_activity > timedelta(minutes=INACTIVITY_MINUTES):
            return "stalled"

    # 🔵 normal
    return "in_progress"

def resolve_no_cuenta(db: Session, folio: str) -> Optional[str]:
    if not folio:
        return None

    venta = obtener_venta_por_folio(db, str(folio))
    if not venta:
        return None

    no_cuenta = venta.get("no_cuenta")
    if not no_cuenta:
        return None

    return str(no_cuenta)


def resolve_cuentas_from_folios(folios: Iterable[str]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}

    for folio in folios:
        try:
            result[str(folio)] = resolve_no_cuenta_cached(str(folio))
        except Exception:
            result[str(folio)] = None

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