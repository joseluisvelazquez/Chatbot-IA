from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.utils.address_formatter import capitalizar_texto
from app.utils.product_mapping import normalize_product_name, product_sku_from_sale

_VERIFICATION_KEYS = {
    "found",
    "folio",
    "sale",
    "sales",
    "customer",
    "account",
    "codigo_cliente",
    "customer_code",
    "ALMARE-1",
    "almare-1",
    "ALMARE_1",
    "almare_1",
    "components",
    "payment_summary",
    "recent_payments",
    "source_table",
}

_CODIGO_CLIENTE_KEYS = (
    "codigo_cliente",
    "customer_code",
    "cod_cliente",
    "cod_cli",
    "ALMARE-1",
    "almare-1",
    "ALMARE_1",
    "almare_1",
)


class BridgeSale:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)
        self._source = "siga_bridge"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip()
        return normalized == "" or normalized.lower() in {"-", "null", "none", "undefined"}
    return False


def _safe_text(value: Any) -> str | None:
    if _is_missing(value) or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text if text else None


def _safe_money(value: Any) -> str | None:
    decimal_value = _decimal_or_none(value)
    return f"{decimal_value:.2f}" if decimal_value is not None else None


def _first_safe_text(records: tuple[dict[str, Any] | None, ...], keys: tuple[str, ...]) -> str | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            text = _safe_text(record.get(key))
            if text:
                return text
    return None


def _normalize_phone(value: Any) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits or text


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


def _value_from_path(record: dict[str, Any] | None, keys: tuple[str, ...]) -> Any | None:
    return _dict_value(record, keys)


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


def _date_text(value: Any) -> str | None:
    parsed = _datetime_or_none(value)
    if parsed:
        return parsed.date().isoformat()
    return _safe_text(value)


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _build_records(data: dict[str, Any]) -> tuple[dict[str, Any] | None, ...]:
    sale = _first_sale(data)
    customer = _as_dict(data.get("customer"))
    account = _as_dict(data.get("account"))
    payment_summary = _as_dict(data.get("payment_summary")) or _as_dict(data.get("payment"))
    return (sale, customer, account, payment_summary, data)


def _format_address_from_record(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None

    direct = _safe_text(
        _value_from_path(record, ("full", "domicilio", "domicilio_completo", "direccion", "address"))
    )
    if direct:
        return capitalizar_texto(direct)

    street = _safe_text(
        _value_from_path(record, ("street", "calle", "nombre_vialidad", "vialidad"))
    )
    external = _safe_text(
        _value_from_path(record, ("external_number", "no_exterior", "no_ext", "numero_exterior", "num_ext"))
    )
    internal = _safe_text(
        _value_from_path(record, ("internal_number", "no_interior", "no_int", "numero_interior", "num_int"))
    )
    neighborhood = _safe_text(_value_from_path(record, ("neighborhood", "colonia")))
    postal_code = _safe_text(_value_from_path(record, ("postal_code", "codigo_postal", "cp")))
    city = _safe_text(_value_from_path(record, ("city", "ciudad_municipio", "ciudad", "municipio", "localidad")))
    state = (
        _safe_text(_value_from_path(record, ("state_name", "estado_nombre")))
        or _safe_text(_value_from_path(record, ("state", "estado")))
    )
    if state and state.isdigit():
        state = None

    parts: list[str] = []
    line1 = " ".join(part for part in (street, external) if part)
    if internal:
        line1 = f"{line1} Int. {internal}".strip()
    if line1:
        parts.append(capitalizar_texto(line1))

    if neighborhood:
        parts.append(f"Col. {capitalizar_texto(neighborhood)}")
    if postal_code:
        parts.append(f"C.P. {postal_code}")

    city_state = ", ".join(
        capitalizar_texto(part)
        for part in (city, state)
        if part
    )
    if city_state:
        parts.insert(0, city_state)

    return ", ".join(parts) if parts else None


def format_bridge_address(*records: dict[str, Any] | None) -> str | None:
    for record in records:
        formatted = _format_address_from_record(record)
        if formatted:
            return formatted
    return None


def _normalize_payment_snapshot(
    data: dict[str, Any],
    records: tuple[dict[str, Any] | None, ...],
) -> dict[str, Any]:
    payment_summary = _as_dict(data.get("payment_summary")) or _as_dict(data.get("payment"))
    account = _as_dict(data.get("account"))
    payment_records = (payment_summary, account, *records)

    saldo = _safe_money(_first_value(payment_records, ("saldo", "balance", "saldo_actual", "saldo_restante")))
    plan_label = _first_safe_text(payment_records, ("plan_label", "plan", "periodicidad", "frecuencia_pago"))
    pago_inicial = _safe_money(
        _first_value(payment_records, ("pago_inicial", "pago", "enganche", "initial_payment", "down_payment"))
    )
    pago_minimo = _safe_money(_first_value(payment_records, ("pago_minimo", "minimum_payment", "pago_semanal")))
    importe_quincenal = _safe_money(_first_value(payment_records, ("importe_quincenal", "pago_quincenal")))
    importe_mensual = _safe_money(_first_value(payment_records, ("importe_mensual", "pago_mensual")))
    subsidio = _safe_money(_first_value(payment_records, ("subsidio", "descuento")))
    saldo_3_meses = _safe_money(_first_value(payment_records, ("saldo_3_meses", "saldo_3m", "saldo_plan_3_meses")))
    fecha_limite_3_meses = _date_text(
        _first_value(payment_records, ("fecha_limite_3_meses", "fecha_limite_3m", "limite_3_meses"))
    )
    importe_semanal_3m = _safe_money(
        _first_value(payment_records, ("importe_semanal_3m", "pago_semanal_3m", "semanal_3_meses"))
    )

    recent_payments = data.get("recent_payments")
    payments_count = len(recent_payments) if isinstance(recent_payments, list) else 0
    available = any(
        [
            saldo,
            plan_label,
            pago_inicial,
            pago_minimo,
            importe_quincenal,
            importe_mensual,
            subsidio,
            saldo_3_meses,
            fecha_limite_3_meses,
            importe_semanal_3m,
            payments_count,
        ]
    )

    return {
        "available": bool(available),
        "saldo": saldo,
        "plan_label": plan_label,
        "pago_inicial": pago_inicial,
        "importe_pago_inicial": pago_inicial,
        "pago_minimo": pago_minimo,
        "importe_quincenal": importe_quincenal,
        "importe_mensual": importe_mensual,
        "subsidio": subsidio,
        "saldo_3_meses": saldo_3_meses,
        "fecha_limite_3_meses": fecha_limite_3_meses,
        "importe_semanal_3m": importe_semanal_3m,
        "payments_count": payments_count,
        "reason": None if available else "payment_data_unavailable",
    }


def _normalize_components_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    components = data.get("components")
    items: list[Any] = []
    if isinstance(components, dict) and isinstance(components.get("items"), list):
        components = components.get("items")

    if isinstance(components, list):
        for item in components:
            if isinstance(item, dict):
                sanitized = {
                    str(key): text
                    for key, value in item.items()
                    if (text := _safe_text(value)) is not None
                }
                if sanitized:
                    items.append(sanitized)
            else:
                text = _safe_text(item)
                if text:
                    items.append(text)
    elif isinstance(components, dict):
        for key, value in components.items():
            text = _safe_text(value)
            if text:
                items.append({"name": str(key), "value": text})

    return {
        "available": bool(items),
        "items": items,
    }


def _codigo_cliente_from_records(records: tuple[dict[str, Any] | None, ...]) -> str | None:
    return _first_safe_text(records, _CODIGO_CLIENTE_KEYS)


def extract_codigo_cliente_from_payload(payload: Any) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)) else payload

    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), None)

    if not isinstance(data, dict):
        return None

    if normalize_bridge_verification_payload(payload):
        snapshot = normalize_siga_verification_snapshot(payload)
        return _safe_text(snapshot.get("codigo_cliente"))

    account = _as_dict(data.get("account"))
    customer = _as_dict(data.get("customer"))
    sale = _as_dict(data.get("sale"))
    return _codigo_cliente_from_records((account, customer, sale, data))


def normalize_siga_verification_snapshot(
    payload: Any,
    *,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    data = normalize_bridge_verification_payload(payload)
    source = _as_dict(data.get("source")) if isinstance(data, dict) else None
    fetched_at = (
        fetched_at
        or _safe_text(source.get("fetched_at") if source else None)
        or datetime.now(timezone.utc).isoformat()
    )
    if not data:
        return {
            "found": False,
            "folio": None,
            "no_cuenta": None,
            "codigo_cliente": None,
            "fecha_venta": None,
            "phone": None,
            "customer": {
                "name": None,
                "codigo_cliente": None,
                "customer_code": None,
                "address_text": None,
                "address_raw": None,
            },
            "sale": {"product": None, "sale_date": None, "fecha_venta": None},
            "payment": {
                "available": False,
                "saldo": None,
                "plan_label": None,
                "pago_inicial": None,
                "importe_pago_inicial": None,
                "pago_minimo": None,
                "importe_quincenal": None,
                "importe_mensual": None,
                "subsidio": None,
                "saldo_3_meses": None,
                "fecha_limite_3_meses": None,
                "importe_semanal_3m": None,
                "payments_count": 0,
                "reason": "payload_unavailable",
            },
            "components": {"available": False, "items": []},
            "source": {"table": None, "fetched_at": fetched_at},
        }

    records = _build_records(data)
    sale, customer, account, payment_summary, _data = records
    address_raw = (
        _as_dict(_dict_value(customer, ("address", "domicilio", "direccion")))
        or _as_dict(_dict_value(sale, ("address", "domicilio", "direccion")))
        or customer
        or sale
    )
    address_text = (
        _safe_text(_dict_value(customer, ("address_text", "domicilio_texto")))
        or format_bridge_address(address_raw, customer, sale, account, data)
    )
    product_sku = product_sku_from_sale(records)
    product_description = _first_safe_text(
        records,
        ("descripcion", "description"),
    )
    product = normalize_product_name(records)
    sale_date = _date_text(
        _first_value(records, ("sale_date", "fecha_venta", "fecha", "created_at"))
    )
    codigo_cliente = _codigo_cliente_from_records(records)

    return {
        "found": bridge_verification_found(data),
        "folio": _first_safe_text(records, ("folio",)),
        "no_cuenta": _first_safe_text(
            records,
            ("no_cuenta", "cuenta", "account", "account_number", "numero_cuenta"),
        ),
        "codigo_cliente": codigo_cliente,
        "fecha_venta": sale_date,
        "phone": _normalize_phone(
            _first_value(records, ("phone", "telefono", "tel_1", "tel1", "celular"))
        ),
        "customer": {
            "name": _first_safe_text(
                records,
                ("name", "nombre", "nombre_completo", "cliente", "customer_name"),
            ),
            "codigo_cliente": codigo_cliente,
            "customer_code": codigo_cliente,
            "address_text": address_text,
            "address_raw": address_raw if isinstance(address_raw, dict) else None,
        },
        "sale": {
            "product": product,
            "product_sku": product_sku,
            "product_description": product_description,
            "sale_date": sale_date,
            "fecha_venta": sale_date,
        },
        "payment": _normalize_payment_snapshot(data, records),
        "components": _normalize_components_snapshot(data),
        "source": {
            "table": _safe_text(data.get("source_table"))
            or _safe_text(source.get("table") if source else None),
            "fetched_at": fetched_at,
        },
    }


def bridge_sale_from_payload(payload: Any) -> BridgeSale | None:
    snapshot = normalize_siga_verification_snapshot(payload)
    if not snapshot.get("found"):
        return None

    folio = _safe_text(snapshot.get("folio"))
    no_cuenta = _safe_text(snapshot.get("no_cuenta"))
    if not folio and not no_cuenta:
        return None

    payment = snapshot.get("payment") if isinstance(snapshot.get("payment"), dict) else {}
    customer = snapshot.get("customer") if isinstance(snapshot.get("customer"), dict) else {}
    sale = snapshot.get("sale") if isinstance(snapshot.get("sale"), dict) else {}
    product_sku = sale.get("product_sku") or product_sku_from_sale(sale)
    product_name = sale.get("product") or normalize_product_name(sale)

    return BridgeSale(
        id_venta_b=None,
        id_emp_bv=None,
        id_movimiento_bv=None,
        folio=folio or "",
        no_cuenta=no_cuenta or "",
        codigo_cliente=_safe_text(snapshot.get("codigo_cliente")),
        nombre_completo=customer.get("name") or "",
        sku_bitacora_v=product_sku or product_name or "",
        descripcion=sale.get("product_description") or product_name or "",
        nombre_producto=product_name or "",
        fecha_venta=_datetime_or_none(sale.get("sale_date") or sale.get("fecha_venta") or snapshot.get("fecha_venta")),
        pago=_decimal_or_none(payment.get("pago_inicial")),
        subsidio=_decimal_or_none(payment.get("subsidio")),
        source_table=(snapshot.get("source") or {}).get("table"),
        _bridge_payload=snapshot,
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
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    return {
        "payload_type": type(payload).__name__,
        "keys": sorted(str(key) for key in data.keys()),
        "found": bridge_verification_found(data),
        "source_table": data.get("source_table") or source.get("table"),
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
    snapshot = normalize_siga_verification_snapshot(payload, fetched_at=updated_at)

    siga_payload["verification_lookup"] = {
        "source": "siga_bridge_v1",
        "lookup_type": "folio",
        "authoritative": True,
        "updated_at": updated_at,
        "folio": str(folio or ""),
        "found": bool(found),
        "data": snapshot,
        "summary": bridge_sale_summary(snapshot),
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

    cache_row = siga_payload.get("verification_cache")
    if isinstance(cache_row, dict):
        if folio and str(cache_row.get("folio") or "") != str(folio):
            return None
        snapshot = cache_row.get("snapshot")
        if isinstance(snapshot, dict):
            return snapshot

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
    direct = _safe_text(_dict_value(customer, ("address_text", "domicilio_texto")))
    if direct:
        return direct

    address_raw = (
        _as_dict(_dict_value(customer, ("address", "domicilio", "direccion")))
        or _as_dict(_dict_value(sale, ("address", "domicilio", "direccion")))
    )
    return format_bridge_address(address_raw, customer, sale, account, data) or "No disponible"


def bridge_address_from_session(session: Any, folio: str | None = None) -> str:
    return bridge_address_from_payload(get_cached_bridge_verification_payload(session, folio))
