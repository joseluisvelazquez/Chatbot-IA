from __future__ import annotations

from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.db.models import Inconsistencias
from sqlalchemy.orm.attributes import flag_modified


FOLIO_FALLBACK = "SIN_FOLIO"


def _deep_merge(base: dict, patch: dict) -> dict:
    """
    Merge normal (dicts anidados).
    """
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _apply_append_ops(extra_json: dict, patch: dict) -> dict:
    """
    Soporta formato especial con sufijo _append:
      {"inconsistencias_append": [{...}]}  → agrega a extra_json["inconsistencias"]
      {"contador": {...}}                  → reemplaza completo (preserva orden)
      {"_delete_keys": ["clave"]}          → elimina claves de extra_json
    """
    # Claves que siempre se reemplazan completas (no deep-merge) para preservar orden
    REPLACE_KEYS = {"contador"}

    # Procesar eliminaciones primero
    for key in patch.get("_delete_keys", []):
        extra_json.pop(key, None)

    for k, v in patch.items():
        if k == "_delete_keys":
            continue  # ya procesado

        if k.endswith("_append") and isinstance(v, list):
            real_key = k.replace("_append", "")
            current_list = extra_json.get(real_key, [])
            if not isinstance(current_list, list):
                current_list = []

            for item in v:
                if isinstance(item, dict):
                    current_list.append(item)
                elif item not in current_list:
                    current_list.append(item)

            extra_json[real_key] = current_list

        elif k in REPLACE_KEYS:
            # Reemplazar completo para preservar el orden de claves
            extra_json[k] = v

        elif isinstance(v, dict) and isinstance(extra_json.get(k), dict):
            extra_json[k] = _deep_merge(extra_json[k], v)

        else:
            extra_json[k] = v

    return extra_json


def get_open_inconsistencia(
    db: Session,
    phone: str,
    folio: str,
    session_id: Optional[int] = None,
) -> Optional[Inconsistencias]:
    q = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.phone == phone)
        .filter(Inconsistencias.folio == folio)
        .filter(Inconsistencias.estatus == "ABIERTA")
    )
    if session_id is not None:
        q = q.filter(Inconsistencias.session_id == session_id)

    return q.order_by(Inconsistencias.id.desc()).first()


def open_or_patch_inconsistencia(
    db: Session,
    phone: str,
    folio: Optional[str],
    session_id: Optional[int],
    patch: dict,
) -> Inconsistencias:
    folio_safe = folio or FOLIO_FALLBACK

    inc = get_open_inconsistencia(db, phone=phone, folio=folio_safe, session_id=session_id)

    if not inc:
        inc = Inconsistencias(
            phone=phone,
            folio=folio_safe,
            session_id=session_id,
            estatus="ABIERTA",
            extra_json={},
        )
        db.add(inc)
        db.flush()

    # aplicar patch
    current = inc.extra_json or {}
    current = _apply_append_ops(current, patch)
    inc.extra_json = current
    flag_modified(inc, "extra_json")

    return inc


def close_open_inconsistencia(
    db: Session,
    phone: str,
    folio: Optional[str],
    session_id: Optional[int] = None,
) -> Optional[Inconsistencias]:
    folio_safe = folio or FOLIO_FALLBACK
    inc = get_open_inconsistencia(db, phone=phone, folio=folio_safe, session_id=session_id)
    if not inc:
        return None
    inc.estatus = "CERRADA"
    return inc


def mark_panel_resolution(
    db: Session,
    inconsistencia_id: int,
    resolved: bool,
) -> Inconsistencias:
    inc = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.id == inconsistencia_id)
        .with_for_update()
        .first()
    )

    if not inc:
        raise ValueError("inconsistencia no encontrada")

    inc.resolved_by_panel = bool(resolved)

    if bool(resolved):
        inc.estatus = "CERRADA"
    return inc
