from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.utils.address_formatter import capitalizar_texto

_VERIFICATION_KEYS = {
    "found",
    "folio",
    "sale",
    "sales",
    "customer",
    "account",
    "components",
    "payment_summary",
    "recent_payments",
    "source_table",
}


class BridgeSale:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)
        self._source = "siga_bridge"


def normalize_bridge_verification_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    data = payload.get("data")
    if isinstance(data, dict) and any(key in data for key in _VERIFICATION_KEYS):
        return data

    if any(key in payload for key in _VERIFICATION_KEYS):
        return payload

    return payload if payload.get("found") is not None else None


def bridge_verification_found(payload: Any) -> bool:
    data = normalize_bridge_verification_payload(payload)
    if not data:
        return False

    if data.get("found") is True:
        return True
    if data.get("found") is False:
        return False

    sale = data.get("sale")
    if isinstance(sale, dict) and sale:
        return True

    sales = data.get("sales")
    return isinstance(sales, list) and any(isinstance(item, dict) and item for item in sales)


def _first_sale(data: dict[str, Any]) -> dict[str, Any] | None:
    sale = data.get("sale")
    if isinstance(sale, dict) and sale:
        return sale

    sales = data.get("sales")
    if isinstance(sales, list):
        for item in sales:
            if isinstance(item, dict) and item:
                return item

    return None


def _dict_value(record: dict[str, Any] | None, keys: tuple[str, ...]) -> Any | None:
    if not isinstance(record, dict):
        return None

    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value

    return None


def _first_value(records: tuple[dict[str, Any] | None, ...], keys: tuple[str, ...]) -> Any | None:
    for record in records:
        value = _dict_value(record, keys)
        if value not in (None, ""):
            return value
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def bridge_sale_from_payload(payload: Any) -> BridgeSale | None:
    data = normalize_bridge_verification_payload(payload)
    if not data or not bridge_verification_found(data):
        return None

    sale = _first_sale(data)
    if not sale:
        return None

    customer = data.get("customer") if isinstance(data.get("customer"), dict) else None
    account = data.get("account") if isinstance(data.get("account"), dict) else None
    payment_summary = (
        data.get("payment_summary")
        if isinstance(data.get("payment_summary"), dict)
        else None
    )
    records = (sale, customer, account, payment_summary, data)

    no_cuenta = _first_value(
        records,
        ("no_cuenta", "cuenta", "account", "account_number", "numero_cuenta"),
    )
    nombre = _first_value(
        records,
        ("nombre_completo", "name", "nombre", "cliente", "customer_name"),
    )
    sku = _first_value(
        records,
        ("sku_bitacora_v", "sku", "codigo", "codigo_barras_bv", "producto_sku"),
    )
    descripcion = _first_value(
        records,
        ("descripcion", "description", "producto", "product", "nombre_producto"),
    )
    fecha_venta = _datetime_or_none(
        _first_value(records, ("fecha_venta", "fecha", "sale_date", "created_at"))
    )
    pago = _decimal_or_none(
        _first_value(
            records,
            ("pago", "pago_inicial", "enganche", "initial_payment", "down_payment"),
        )
    )
    subsidio = _decimal_or_none(_first_value(records, ("subsidio", "descuento")))

    return BridgeSale(
        id_venta_b=_first_value(records, ("id_venta_b", "id_venta", "id")),
        id_emp_bv=_first_value(records, ("id_emp_bv", "id_emp", "company_id")),
        id_movimiento_bv=_first_value(
            records,
            ("id_movimiento_bv", "id_movimiento", "movimiento"),
        ),
        folio=str(_first_value(records, ("folio",)) or ""),
        no_cuenta=str(no_cuenta or ""),
        nombre_completo=str(nombre or ""),
        sku_bitacora_v=str(sku or descripcion or ""),
        descripcion=str(descripcion or sku or ""),
        fecha_venta=fecha_venta,
        pago=pago,
        subsidio=subsidio,
        source_table=data.get("source_table"),
        _bridge_payload=data,
    )


def bridge_sale_summary(payload: Any) -> dict[str, Any]:
    data = normalize_bridge_verification_payload(payload)
    if not data:
        return {
            "payload_type": type(payload).__name__,
            "found": False,
        }

    sale = data.get("sale")
    sales = data.get("sales")
    return {
        "payload_type": type(payload).__name__,
        "keys": sorted(str(key) for key in data.keys()),
        "found": bridge_verification_found(data),
        "source_table": data.get("source_table"),
        "has_sale": isinstance(sale, dict) and bool(sale),
        "sales_count": len(sales) if isinstance(sales, list) else None,
        "has_customer": isinstance(data.get("customer"), dict),
        "has_account": isinstance(data.get("account"), dict),
        "has_payment_summary": isinstance(data.get("payment_summary"), dict),
        "recent_payments_count": (
            len(data.get("recent_payments"))
            if isinstance(data.get("recent_payments"), list)
            else None
        ),
    }


def is_bridge_sale(value: Any) -> bool:
    return isinstance(value, BridgeSale) or getattr(value, "_source", None) == "siga_bridge"


def cache_bridge_verification_on_session(
    session: Any,
    *,
    folio: str,
    payload: Any,
    found: bool,
    updated_at: str,
) -> None:
    if session is None:
        return

    current = getattr(session, "extra_json", None)
    current_payload = dict(current) if isinstance(current, dict) else {}
    siga_payload = dict(current_payload.get("siga_bridge") or {})

    siga_payload["verification_lookup"] = {
        "source": "siga_bridge_v1",
        "lookup_type": "folio",
        "authoritative": True,
        "updated_at": updated_at,
        "folio": str(folio or ""),
        "found": bool(found),
        "data": payload,
        "summary": bridge_sale_summary(payload),
    }
    current_payload["siga_bridge"] = siga_payload
    session.extra_json = current_payload

    try:
        flag_modified(session, "extra_json")
    except Exception:
        pass


def get_cached_bridge_verification_payload(
    session: Any,
    folio: str | None = None,
) -> Any | None:
    extra = getattr(session, "extra_json", None)
    if not isinstance(extra, dict):
        return None

    siga_payload = extra.get("siga_bridge")
    if not isinstance(siga_payload, dict):
        return None

    lookup = siga_payload.get("verification_lookup")
    if not isinstance(lookup, dict):
        return None

    if folio and str(lookup.get("folio") or "") != str(folio):
        return None

    return lookup.get("data")


def bridge_sale_from_session(session: Any, folio: str | None = None) -> BridgeSale | None:
    return bridge_sale_from_payload(get_cached_bridge_verification_payload(session, folio))


def bridge_address_from_payload(payload: Any) -> str:
    data = normalize_bridge_verification_payload(payload)
    if not data:
        return "No disponible"

    sale = _first_sale(data)
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else None
    account = data.get("account") if isinstance(data.get("account"), dict) else None
    records = (sale, customer, account, data)

    direct = _first_value(
        records,
        ("domicilio", "domicilio_completo", "direccion", "address"),
    )
    if direct:
        return capitalizar_texto(str(direct))

    calle = _first_value(records, ("calle", "nombre_vialidad", "vialidad"))
    no_ext = _first_value(records, ("no_ext", "numero_exterior", "num_ext"))
    no_int = _first_value(records, ("no_int", "numero_interior", "num_int"))
    colonia = _first_value(records, ("colonia", "colony"))
    cp = _first_value(records, ("codigo_postal", "cp", "postal_code"))
    ciudad = _first_value(records, ("ciudad", "municipio", "localidad", "city"))
    estado = _first_value(records, ("estado", "state"))

    parts: list[str] = []
    line1 = " ".join(str(item).strip() for item in (calle, no_ext) if item)
    if no_int:
        line1 = f"{line1} Int. {str(no_int).strip()}".strip()
    if line1:
        parts.append(capitalizar_texto(line1))

    if colonia and cp:
        parts.append(f"Col. {capitalizar_texto(str(colonia))} C.P. {str(cp).strip()}")
    elif colonia:
        parts.append(f"Col. {capitalizar_texto(str(colonia))}")
    elif cp:
        parts.append(f"C.P. {str(cp).strip()}")

    city_state = ", ".join(
        capitalizar_texto(str(item))
        for item in (ciudad, estado)
        if item not in (None, "")
    )
    if city_state:
        parts.append(city_state)

    return ", ".join(parts) if parts else "No disponible"


def bridge_address_from_session(session: Any, folio: str | None = None) -> str:
    return bridge_address_from_payload(get_cached_bridge_verification_payload(session, folio))
