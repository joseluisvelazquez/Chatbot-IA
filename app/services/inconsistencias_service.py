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
    Soporta formato especial:
      {"componentes": {"faltantes_append": ["Monitor"]}}
    que se vuelve:
      extra_json["componentes"]["faltantes"] = [..., "Monitor"] (sin duplicados)
    """
    for section_key, section_patch in patch.items():
        if not isinstance(section_patch, dict):
            # merge normal
            extra_json[section_key] = section_patch
            continue

        section = extra_json.get(section_key, {})
        if not isinstance(section, dict):
            section = {}

        for k, v in section_patch.items():
            if k.endswith("_append") and isinstance(v, list):
                real_key = k.replace("_append", "")
                current_list = section.get(real_key, [])
                if not isinstance(current_list, list):
                    current_list = []

                for item in v:
                    if item not in current_list:
                        current_list.append(item)

                section[real_key] = current_list
            else:
                # merge normal dentro de la sección
                if isinstance(v, dict) and isinstance(section.get(k), dict):
                    section[k] = _deep_merge(section[k], v)
                else:
                    section[k] = v

        extra_json[section_key] = section

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