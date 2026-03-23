from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from app.core.verification_steps import STEP_ORDER
from app.core.verification_schema import normalize_progress_payload
from app.siga.siga_repository import obtener_venta_por_folio


INACTIVITY_MINUTES = 30


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

@lru_cache(maxsize=1000)
def resolve_no_cuenta_cached(folio: str) -> Optional[str]:
    if not folio:
        return None

    venta = obtener_venta_por_folio(str(folio))
    if not venta:
        return None

    no_cuenta = venta.get("no_cuenta")
    if no_cuenta in (None, ""):
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
        # Ajusta este bloque si tu modelo usa otro nombre de campo
        if hasattr(item, "activa"):
            if bool(getattr(item, "activa")):
                return True
        else:
            # Si no existe bandera de cierre, asumimos activa
            return True

    return False