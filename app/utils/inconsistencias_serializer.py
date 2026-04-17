from __future__ import annotations

from typing import Iterable, Optional

from app.db.models import Inconsistencias

SEVERITY_ORDER = {
    "leve": 1,
    "moderada": 2,
    "critica": 3,
}

RESERVED_EXTRA_KEYS = {
    "evento",
    "contador",
    "inconsistencias",
    "componentes_temp",
    "_panel_resolutions",
}

STATE_FIELD_LABELS = {
    "CONFIRMAR_NOMBRE": "nombre",
    "CONFIRMAR_DOMICILIO": "domicilio",
    "CONFIRMAR_FECHA": "fecha_venta",
    "CONFIRMAR_PRODUCTO": "producto",
    "CONFIRMAR_PAGO_INICIAL": "pago_inicial",
    "CONFIRMAR_COMPONENTES": "componentes",
}


def normalize_severity(value: object) -> Optional[str]:
    if value is None:
        return None

    severity = str(value).strip().lower()
    if severity in SEVERITY_ORDER:
        return severity

    return None


def _normalize_estado(value: object) -> str:
    return str(value or "ABIERTA").strip().upper()


def _normalize_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def _humanize_field(value: object) -> str:
    if value is None:
        return "general"

    text = str(value).strip()
    if not text:
        return "general"

    if text in STATE_FIELD_LABELS:
        return STATE_FIELD_LABELS[text]

    return text.replace("_", " ").strip().lower()


def _build_message(raw_message: object, elementos_faltantes: list[str]) -> str:
    if raw_message is not None and str(raw_message).strip():
        return str(raw_message).strip()

    if elementos_faltantes:
        return f"Faltantes: {', '.join(elementos_faltantes)}"

    return "Sin detalle"


def _build_item(
    *,
    unique_id: str,
    inc_id: int,
    campo: object,
    mensaje: object,
    db_estado: object,
    resolved_by_panel: object,
    resolved_by_siga: object,
    severidad: object = None,
    estado_origen: object = None,
    elementos_faltantes: object = None,
) -> dict:
    missing_items = _normalize_list(elementos_faltantes)
    normalized_field = _humanize_field(campo or estado_origen)

    is_component_issue = (
        str(estado_origen or "").strip().upper() == "CONFIRMAR_COMPONENTES"
        or normalized_field == "componentes"
        or bool(missing_items)
    )

    panel_resolved = bool(resolved_by_panel)
    siga_resolved = bool(resolved_by_siga)

    business_resolved = siga_resolved or panel_resolved

    return {
        "id": inc_id,           #  ID REAL (backend)
        "ui_id": unique_id,     #  ID ÚNICO (frontend)
        "campo": normalized_field,
        "mensaje": _build_message(mensaje, missing_items),
        "estado": "RESUELTA" if business_resolved else "ABIERTA",
        "db_estado": _normalize_estado(db_estado),
        "severidad": normalize_severity(severidad),
        "estado_origen": str(estado_origen).strip() if estado_origen else None,
        "elementos_faltantes": missing_items,
        "resolved_by_panel": panel_resolved,
        "resolved_by_siga": siga_resolved,
        "requires_siga": not is_component_issue,
        "can_resolve_locally": is_component_issue,
        "business_resolved": business_resolved,
    }


def _get_panel_resolution(
    resolutions: object,
    unique_id: str,
    fallback: object,
) -> bool:
    if isinstance(resolutions, dict) and unique_id in resolutions:
        return bool(resolutions.get(unique_id))

    return bool(fallback)

def serialize_inconsistencias(inconsistencias: Iterable[Inconsistencias]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()

    for inc in inconsistencias:
        extra = inc.extra_json or {}
        estatus = inc.estatus or "ABIERTA"

        resolved_by_panel = getattr(inc, "resolved_by_panel", False)
        resolved_by_siga = getattr(inc, "resolved_by_siga", False)
        panel_resolutions = extra.get("_panel_resolutions")

        base_id = getattr(inc, "id", None)

        # =========================================
        # 1. INCONSISTENCIAS ANIDADAS
        # =========================================
        nested_items = extra.get("inconsistencias")

        if isinstance(nested_items, list):
            for idx, entry in enumerate(nested_items):
                if not isinstance(entry, dict):
                    continue

                unique_id = f"{base_id}:nested:{idx}"

                item = _build_item(
                    unique_id=unique_id,
                    inc_id=base_id,
                    campo=entry.get("campo"),
                    mensaje=entry.get("mensaje_cliente") or entry.get("mensaje"),
                    db_estado=estatus,
                    resolved_by_panel=_get_panel_resolution(
                        panel_resolutions,
                        unique_id,
                        resolved_by_panel,
                    ),
                    resolved_by_siga=resolved_by_siga,
                    severidad=entry.get("severidad"),
                    estado_origen=entry.get("estado_origen"),
                    elementos_faltantes=entry.get("elementos_faltantes"),
                )

                if unique_id in seen:
                    continue

                seen.add(unique_id)
                result.append(item)

        # =========================================
        # 2. CAMPOS SUELTOS
        # =========================================
        for idx, (field_name, field_data) in enumerate(extra.items()):
            if field_name in RESERVED_EXTRA_KEYS or not isinstance(field_data, dict):
                continue

            mensaje_cliente = field_data.get("mensaje_cliente") or field_data.get("mensaje")
            confirmado = field_data.get("confirmado")

            faltantes = (
                field_data.get("elementos_faltantes")
                or field_data.get("faltantes")
            )

            if confirmado is not False and not mensaje_cliente and not faltantes:
                continue

            unique_id = f"{base_id}:field:{idx}"

            item = _build_item(
                unique_id=unique_id,
                inc_id=base_id,
                campo=field_name,
                mensaje=mensaje_cliente,
                db_estado=estatus,
                resolved_by_panel=_get_panel_resolution(
                    panel_resolutions,
                    unique_id,
                    resolved_by_panel,
                ),
                resolved_by_siga=resolved_by_siga,
                severidad=field_data.get("severidad"),
                estado_origen=field_data.get("estado_origen"),
                elementos_faltantes=faltantes,
            )

            if unique_id in seen:
                continue

            seen.add(unique_id)
            result.append(item)

    return result


def summarize_inconsistencias(items: Iterable[dict]) -> dict:
    serialized = list(items)
    open_items = [
        item
        for item in serialized
        if _normalize_estado(item.get("estado")) == "ABIERTA"
    ]

    severity_counts = {
        "leve": 0,
        "moderada": 0,
        "critica": 0,
        "total": len(open_items),
    }

    highest_severity: Optional[str] = None
    highest_priority = 0

    for item in open_items:
        severity = normalize_severity(item.get("severidad"))
        if severity:
            severity_counts[severity] += 1

    for item in open_items:
        severity = normalize_severity(item.get("severidad"))
        if not severity:
            continue

        priority = SEVERITY_ORDER[severity]
        if priority > highest_priority:
            highest_priority = priority
            highest_severity = severity

    return {
        "severity_counts": severity_counts,
        "highest_severity": highest_severity,
    }
