from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import unicodedata
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.security.auth_service import get_nombre_resumido
from app.services.siga_bridge import SigaBridgeError, get_siga_bridge_client
from app.services.siga_navigation import build_siga_account_url

logger = logging.getLogger(__name__)

COLLECTION_ROLES = {"admin", "cobranza", "jefe_operativo", "sistemas"}
GESTOR_FILTER_ROLES = {"admin", "jefe_operativo", "sistemas"}
CLASSIFICATIONS = {"sano", "critico", "pagado", "otro"}
STATUS_FILTERS = CLASSIFICATIONS | {"all"}
DEFAULT_COLLECTION_LIMIT = 25
MAX_COLLECTION_LIMIT = 50
CRITICAL_OVERDUE_DAYS = 30


@dataclass(frozen=True)
class CollectionFilters:
    account: str | None = None
    folio: str | None = None
    phone: str | None = None
    name: str | None = None
    status: str | None = None
    classification: str | None = None
    gestor: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    overdue_only: bool = False
    paid_only: bool = False
    include_paid: bool = False
    active_only: bool = True
    limit: int = DEFAULT_COLLECTION_LIMIT
    offset: int = 0


def can_view_collections(user: Any) -> bool:
    return getattr(user, "role", None) in COLLECTION_ROLES


def can_filter_collections_by_gestor(user: Any) -> bool:
    return getattr(user, "role", None) in GESTOR_FILTER_ROLES


def build_collection_filters(
    *,
    account: str | None = None,
    folio: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    status: str | None = None,
    classification: str | None = None,
    gestor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    overdue_only: bool = False,
    paid_only: bool = False,
    include_paid: bool = False,
    active_only: bool = True,
    limit: int = DEFAULT_COLLECTION_LIMIT,
    offset: int = 0,
) -> CollectionFilters:
    def clean_text(value: str | None, *, max_len: int = 120) -> str | None:
        if value is None:
            return None
        text_value = re.sub(r"\s+", " ", str(value)).strip()
        if not text_value:
            return None
        if len(text_value) > max_len:
            raise ValueError("Filtro demasiado largo")
        if any(ord(ch) < 32 for ch in text_value):
            raise ValueError("Filtro invalido")
        return text_value

    def clean_lookup(value: str | None, name: str) -> str | None:
        text_value = clean_text(value, max_len=50)
        if text_value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", text_value):
            raise ValueError(f"{name} invalido")
        return text_value

    def clean_phone(value: str | None) -> str | None:
        text_value = clean_text(value, max_len=20)
        if text_value is None:
            return None
        digits = re.sub(r"\D+", "", text_value)
        if not 3 <= len(digits) <= 15:
            raise ValueError("telefono invalido")
        return digits

    def clean_date(value: str | None, name: str) -> str | None:
        text_value = clean_text(value, max_len=10)
        if text_value is None:
            return None
        try:
            date.fromisoformat(text_value)
        except ValueError as exc:
            raise ValueError(f"{name} invalida") from exc
        return text_value

    normalized_status = clean_text(status or classification, max_len=20)
    if normalized_status:
        normalized_status = _strip_accents(normalized_status.lower())
        if normalized_status == "juridico":
            normalized_status = "critico"
        if normalized_status not in STATUS_FILTERS:
            raise ValueError("estado invalido")

    normalized_include_paid = bool(
        include_paid
        or paid_only
        or normalized_status in {"pagado", "all"}
    )
    normalized_active_only = bool(active_only)
    if normalized_include_paid or normalized_status in {"pagado", "all"}:
        normalized_active_only = False

    normalized_limit = max(1, min(MAX_COLLECTION_LIMIT, int(limit or DEFAULT_COLLECTION_LIMIT)))
    normalized_offset = max(0, int(offset or 0))

    return CollectionFilters(
        account=clean_lookup(account, "cuenta"),
        folio=clean_lookup(folio, "folio"),
        phone=clean_phone(phone),
        name=clean_text(name),
        status=normalized_status,
        classification=normalized_status if normalized_status != "all" else None,
        gestor=clean_text(gestor, max_len=120),
        date_from=clean_date(date_from, "fecha inicial"),
        date_to=clean_date(date_to, "fecha final"),
        overdue_only=bool(overdue_only),
        paid_only=bool(paid_only),
        include_paid=normalized_include_paid,
        active_only=normalized_active_only,
        limit=normalized_limit,
        offset=normalized_offset,
    )


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _safe_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text_value = re.sub(r"\s+", " ", str(value)).strip()
    if not text_value or text_value.lower() in {"-", "null", "none", "undefined", "[object object]"}:
        return None
    return text_value


def _clean_manager_search(value: str | None, *, max_len: int = 80) -> str | None:
    if value is None:
        return None
    text_value = re.sub(r"\s+", " ", str(value)).strip()
    if not text_value:
        return None
    if len(text_value) > max_len or any(ord(ch) < 32 for ch in text_value):
        raise ValueError("busqueda de gestor invalida")
    return text_value


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
        if not value:
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Any) -> str | None:
    decimal_value = _safe_decimal(value)
    return f"{decimal_value:.2f}" if decimal_value is not None else None


def _number(value: Any) -> int | float | None:
    decimal_value = _safe_decimal(value)
    if decimal_value is None:
        return None
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _date_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _safe_text(value)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        text_value = _safe_text(value)
        if text_value:
            return text_value
    return None


def _first_money(*values: Any) -> str | None:
    for value in values:
        money_value = _money(value)
        if money_value is not None:
            return money_value
    return None


def _first_number(*values: Any) -> int | float | None:
    for value in values:
        number_value = _number(value)
        if number_value is not None:
            return number_value
    return None


def _first_date(*values: Any) -> str | None:
    for value in values:
        text_value = _date_text(value)
        if text_value:
            return text_value
    return None


def _append_phone(phones: list[str], value: Any) -> None:
    text_value = _safe_text(value)
    if not text_value:
        return
    if text_value not in phones:
        phones.append(text_value)


def _extract_phones(*records: Mapping[str, Any]) -> list[str]:
    phones: list[str] = []
    for record in records:
        if not record:
            continue
        raw_phones = record.get("phones")
        if isinstance(raw_phones, list):
            for phone in raw_phones:
                _append_phone(phones, phone)
        for key in (
            "phone",
            "telefono",
            "telefono_principal",
            "tel_1",
            "tel_2",
            "tel_3",
            "tel1",
            "tel2",
            "tel3",
            "telefonodl",
            "customer_phone_1",
            "customer_phone_2",
            "customer_phone_3",
            "customer_phone_dl",
            "sale_phone_1",
            "sale_phone_2",
            "sale_phone_3",
        ):
            _append_phone(phones, record.get(key))
    return phones


def _classification(
    *,
    status: str | None,
    process: str | None,
    balance: Any,
    days_overdue: Any = None,
    overdue_amount: Any = None,
    late_fee: Any = None,
) -> tuple[str, str]:
    text_value = _strip_accents(f"{status or ''} {process or ''}".lower())
    balance_value = _safe_decimal(balance)
    days_value = _safe_decimal(days_overdue) or Decimal("0")
    overdue_value = _safe_decimal(overdue_amount) or Decimal("0")
    late_fee_value = _safe_decimal(late_fee) or Decimal("0")

    if (
        (balance_value is not None and balance_value <= 0)
        or "pagad" in text_value
        or "liquidad" in text_value
    ):
        return "pagado", "Pagado"
    if (
        "jurid" in text_value
        or "critic" in text_value
        or "mora" in text_value
        or overdue_value > 0
        or late_fee_value > 0
        or days_value >= CRITICAL_OVERDUE_DAYS
    ):
        return "critico", "Critico"
    if "sano" in text_value or (
        _first_text(status, process)
        and "cancel" not in text_value
        and "inactiv" not in text_value
        and overdue_value <= 0
        and late_fee_value <= 0
        and days_value <= 0
    ):
        return "sano", "Sano"

    label = _first_text(process, status) or "Otro"
    return "otro", label


def normalize_payment(record: Any) -> dict[str, Any] | None:
    payment = _as_mapping(record)
    if not payment:
        return None

    return {
        "id": _first_text(payment.get("id")),
        "account": _first_text(payment.get("account"), payment.get("cuenta_e")),
        "concept": _first_text(payment.get("concept"), payment.get("concepto")),
        "product": _first_text(payment.get("product"), payment.get("producto_s")),
        "payment_method": _first_text(payment.get("payment_method"), payment.get("metodo_pago")),
        "amount": _first_money(payment.get("amount"), payment.get("cantidad")),
        "paid_at": _first_date(payment.get("paid_at"), payment.get("fecha_pago")),
        "balance_after_payment": _first_money(
            payment.get("balance_after_payment"),
            payment.get("saldo"),
        ),
        "user": _first_text(payment.get("user"), payment.get("usuario")),
    }


def normalize_payments(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = (
            payload.get("payments")
            or payload.get("pagos")
            or payload.get("items")
            or payload.get("data")
            or []
        )
    else:
        raw_items = []

    if not isinstance(raw_items, list):
        return []

    return [payment for item in raw_items if (payment := normalize_payment(item))]


def normalize_collection_record(
    record: Any,
    *,
    payments: list[dict[str, Any]] | None = None,
    source: str = "siga_bridge",
    bridge_status: str = "ok",
) -> dict[str, Any] | None:
    item = _as_mapping(record)
    if not item:
        return None

    account_raw = item.get("account")
    account = _as_mapping(account_raw)
    customer = _as_mapping(item.get("customer"))
    sale = _as_mapping(item.get("sale"))
    amounts = _as_mapping(account.get("amounts"))
    plan = _as_mapping(account.get("plan"))
    summary = _as_mapping(
        item.get("payment_summary")
        or item.get("summary")
        or item.get("financial_summary")
        or item.get("payment")
    )
    payment_items = payments if payments is not None else normalize_payments(item.get("payments") or item)

    no_cuenta = _first_text(
        item.get("no_cuenta"),
        item.get("account_number"),
        item.get("cuenta"),
        account.get("account"),
        account.get("cuenta"),
        account.get("no_cuenta"),
        account_raw if not isinstance(account_raw, Mapping) else None,
    )
    if not no_cuenta:
        return None

    balance = _first_money(
        item.get("balance"),
        item.get("debt"),
        item.get("saldo"),
        amounts.get("stored_balance"),
        amounts.get("balance"),
        summary.get("stored_balance"),
        summary.get("saldo"),
        account.get("saldo"),
    )
    overdue_amount = _first_money(
        item.get("overdue_amount"),
        item.get("vencido"),
        amounts.get("overdue"),
        summary.get("overdue"),
    )
    status = _first_text(item.get("account_status"), account.get("status"), account.get("estatus"))
    process = _first_text(item.get("process"), account.get("process"), account.get("proceso"))
    days_overdue = _first_number(
        item.get("days_overdue"),
        item.get("dias_atraso"),
        item.get("atrasos"),
        account.get("atrasos"),
    )
    late_fee = _first_money(item.get("late_fee"), item.get("moratorio"), amounts.get("late_fee"))
    classification, classification_label = _classification(
        status=status,
        process=process,
        balance=balance,
        days_overdue=days_overdue,
        overdue_amount=overdue_amount,
        late_fee=late_fee,
    )
    explicit_classification = _first_text(
        item.get("estado_calculado"),
        item.get("classification"),
    )
    if explicit_classification:
        explicit_classification = _strip_accents(explicit_classification.lower())
    if explicit_classification == "juridico":
        explicit_classification = "critico"
    if explicit_classification in CLASSIFICATIONS:
        classification = explicit_classification
        classification_label = _first_text(item.get("classification_label"), classification_label) or classification

    phones = _extract_phones(item, customer, sale)
    initial_payment = _first_money(
        item.get("initial_payment"),
        item.get("pago_inicial"),
        account.get("initial_payment"),
        summary.get("initial_payment"),
        summary.get("pago_inicial"),
    )
    total_paid = _first_money(
        item.get("total_paid"),
        summary.get("paid_total"),
    )
    if total_paid is None:
        payments_sum_raw = summary.get("payments_sum") if summary else None
        if payments_sum_raw is None:
            payments_sum_raw = item.get("payments_sum")
        if initial_payment is not None or payments_sum_raw is not None:
            initial = _safe_decimal(initial_payment) or Decimal("0")
            payments_sum = _safe_decimal(payments_sum_raw) or Decimal("0")
            total_paid = _money(initial + payments_sum)

    payments_count = _first_number(
        item.get("payments_count"),
        summary.get("payments_count"),
        len(payment_items) if payment_items else None,
    )
    last_payment = _first_date(
        item.get("last_payment"),
        item.get("last_payment_at"),
        item.get("ultimo_pago"),
        item.get("fecha_ultimo_pago"),
        account.get("last_payment_date"),
        summary.get("last_payment_at"),
        payment_items[0].get("paid_at") if payment_items else None,
    )
    has_overdue = bool(
        item.get("has_overdue")
        or (_safe_decimal(overdue_amount) or Decimal("0")) > 0
        or (_safe_decimal(days_overdue) or Decimal("0")) > 0
    )
    is_paid = classification == "pagado"
    status_text = _strip_accents(f"{status or ''} {process or ''}".lower())

    return {
        "no_cuenta": no_cuenta,
        "folio": _first_text(item.get("folio"), sale.get("folio")),
        "phone": _first_text(item.get("phone"), phones[0] if phones else None),
        "phones": phones,
        "customer_name": _first_text(
            item.get("customer_name"),
            item.get("cliente"),
            customer.get("name"),
            customer.get("nombre"),
            customer.get("nombre_completo"),
            sale.get("nombre_completo"),
        ),
        "customer": {
            "name": _first_text(
                item.get("customer_name"),
                item.get("cliente"),
                customer.get("name"),
                customer.get("nombre"),
                customer.get("nombre_completo"),
                sale.get("nombre_completo"),
            ),
            "customer_code": _first_text(
                item.get("customer_code"),
                item.get("cod_cli"),
                account.get("customer_code"),
                customer.get("customer_code"),
            ),
            "phones": phones,
            "address_text": _first_text(
                item.get("address_text"),
                customer.get("address_text"),
                _as_mapping(customer.get("address")).get("full"),
            ),
        },
        "account_status": status,
        "process": process,
        "classification": classification,
        "estado_calculado": classification,
        "classification_label": classification_label,
        "product": _first_text(item.get("product"), account.get("product"), account.get("producto"), sale.get("descripcion")),
        "sale_date": _first_date(
            item.get("sale_date"),
            item.get("fecha_venta"),
            item.get("fecha_relevante"),
            account.get("sale_date"),
            account.get("fecha_venta"),
            sale.get("fecha_venta"),
        ),
        "last_payment": last_payment,
        "balance": balance,
        "debt": _first_money(item.get("debt"), balance),
        "overdue_amount": overdue_amount,
        "days_overdue": days_overdue,
        "total_paid": total_paid,
        "payments_count": int(payments_count or 0),
        "has_overdue": has_overdue,
        "is_paid": is_paid,
        "is_active": bool(not is_paid and "cancel" not in status_text and "inactiv" not in status_text),
        "advisor": _first_text(item.get("advisor"), account.get("advisor"), item.get("asesor")),
        "collector": _first_text(
            item.get("collector"),
            item.get("gestor_cobranza"),
            account.get("collector"),
            item.get("agente_verificador"),
        ),
        "financial_summary": {
            "balance": balance,
            "debt": _first_money(item.get("debt"), balance),
            "overdue_amount": overdue_amount,
            "late_fee": late_fee,
            "liquidation_amount": _first_money(
                item.get("liquidation_amount"),
                item.get("liquida"),
                amounts.get("liquidation"),
                summary.get("liquidation"),
            ),
            "initial_payment": initial_payment,
            "minimum_payment": _first_money(
                item.get("minimum_payment"),
                item.get("pagos_minimos"),
                plan.get("minimum_payment"),
                summary.get("minimum_payment"),
                summary.get("pago_minimo"),
            ),
            "total_paid": total_paid,
            "payments_count": int(payments_count or 0),
        },
        "payments": payment_items,
        "siga_url": build_siga_account_url(no_cuenta, _first_text(item.get("folio"), sale.get("folio"))),
        "source": source,
        "source_table": _first_text(item.get("source_table"), "cuentas"),
        "siga_bridge": {
            "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
            "status": bridge_status,
            "source": source,
            "available": source == "siga_bridge",
        },
    }


def _classification_options(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    options = {
        "sano": "Sano",
        "critico": "Critico",
        "pagado": "Pagado",
        "otro": "Otros estados",
    }
    for item in items:
        if item.get("classification") == "otro" and item.get("classification_label"):
            options["otro"] = "Otros estados"
    return [{"value": key, "label": label} for key, label in options.items()]


def _filters_applied(filters: CollectionFilters, *, collector: str | None = None) -> dict[str, Any]:
    return {
        "limit": filters.limit,
        "offset": filters.offset,
        "status": filters.status,
        "include_paid": filters.include_paid,
        "active_only": filters.active_only,
        "overdue_only": filters.overdue_only,
        "has_account_filter": bool(filters.account),
        "has_folio_filter": bool(filters.folio),
        "has_phone_filter": bool(filters.phone),
        "has_name_filter": bool(filters.name),
        "gestor_scoped": bool(collector),
    }


def _collections_response(
    filters: CollectionFilters,
    *,
    items: list[dict[str, Any]],
    total: int | None,
    source: str,
    bridge_status: str,
    bridge_error: str | None = None,
    warnings: list[str] | None = None,
    collector: str | None = None,
    has_more: bool | None = None,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    computed_has_more = (
        filters.offset + len(items) < total
        if total is not None
        else len(items) >= filters.limit
    )
    has_more = computed_has_more if has_more is None else bool(has_more)
    next_cursor = next_cursor if next_cursor is not None else (str(filters.offset + len(items)) if has_more else None)
    meta = {
        "limit": filters.limit,
        "offset": filters.offset,
        "include_paid": filters.include_paid,
        "active_only": filters.active_only,
        "source": source,
        "bridge_status": bridge_status,
        "filters_applied": _filters_applied(filters, collector=collector),
        "warnings": warnings or [],
    }
    if bridge_error:
        meta["bridge_error"] = bridge_error

    return {
        "ok": True,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "meta": meta,
        "data": items,
        "total": int(total if total is not None else filters.offset + len(items)),
        "source": source,
        "bridge_status": bridge_status,
        "bridge_error": bridge_error,
        "classification_options": _classification_options(items),
        "limit": filters.limit,
        "offset": filters.offset,
    }


def normalize_collection_manager(record: Any) -> dict[str, Any] | None:
    item = _as_mapping(record)
    if not item:
        return None
    value = _first_text(item.get("value"), item.get("gestor"), item.get("collector"))
    if not value:
        return None
    return {
        "value": value,
        "label": _first_text(item.get("label"), value),
        "accounts_count": _first_number(item.get("accounts_count")),
        "source_field": _first_text(item.get("source_field"), "cuentas.agente_verificador"),
    }


def normalize_collection_managers(payload: Any) -> list[dict[str, Any]]:
    data = _as_mapping(payload)
    raw_items = data.get("items") or data.get("data") or data.get("managers") or []
    if not isinstance(raw_items, list):
        return []
    return [manager for row in raw_items if (manager := normalize_collection_manager(row))]


def _empty_response(
    filters: CollectionFilters,
    *,
    source: str,
    bridge_status: str,
    warnings: list[str] | None = None,
    collector: str | None = None,
) -> dict[str, Any]:
    return _collections_response(
        filters,
        items=[],
        total=0,
        source=source,
        bridge_status=bridge_status,
        warnings=warnings,
        collector=collector,
    )


def _authorized_collector(
    db: Session,
    user: Any,
    filters: CollectionFilters,
) -> tuple[str | None, list[str], bool]:
    role = getattr(user, "role", None)
    warnings: list[str] = []

    if role == "cobranza":
        collector = get_nombre_resumido(db, user.username)
        if not collector:
            return None, ["gestor_scope_missing"], False
        if filters.gestor and filters.gestor != collector:
            warnings.append("gestor_filter_ignored_for_role")
        return collector, warnings, True

    if role in GESTOR_FILTER_ROLES:
        return filters.gestor, warnings, True

    if filters.gestor:
        warnings.append("gestor_filter_not_allowed")
    return None, warnings, True


def _scoped_collector(db: Session, user: Any) -> str | None:
    if getattr(user, "role", None) != "cobranza":
        return None
    return get_nombre_resumido(db, user.username)


def _like(value: str) -> str:
    return f"%{value}%"


def _phone_sql(expression: str) -> str:
    return (
        "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
        f"COALESCE({expression}, ''), ' ', ''), '-', ''), '(', ''), ')', ''), '+', ''), '.', '')"
    )


def _paid_condition() -> str:
    return """(
        COALESCE(c.saldo, 0) <= 0
        OR LOWER(COALESCE(c.estatus, '')) LIKE '%pagad%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%pagad%'
        OR LOWER(COALESCE(c.estatus, '')) LIKE '%liquidad%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%liquidad%'
    )"""


def _cancelled_condition() -> str:
    return """(
        LOWER(COALESCE(c.estatus, '')) LIKE '%cancel%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%cancel%'
        OR LOWER(COALESCE(c.estatus, '')) LIKE '%inactiv%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%inactiv%'
    )"""


def _critical_condition() -> str:
    return """(
        LOWER(COALESCE(c.estatus, '')) LIKE '%jurid%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%jurid%'
        OR LOWER(COALESCE(c.estatus, '')) LIKE '%critic%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%critic%'
        OR LOWER(COALESCE(c.estatus, '')) LIKE '%mora%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%mora%'
        OR COALESCE(c.vencido, 0) > 0
        OR COALESCE(c.moratorio, 0) > 0
        OR COALESCE(c.atrasos, 0) >= 30
    )"""


def _sano_condition() -> str:
    return f"""(
        LOWER(COALESCE(c.estatus, '')) LIKE '%sano%'
        OR LOWER(COALESCE(c.proceso, '')) LIKE '%sano%'
        OR (
            NOT {_paid_condition()}
            AND NOT {_critical_condition()}
            AND NOT {_cancelled_condition()}
            AND (
                COALESCE(c.estatus, '') <> ''
                OR COALESCE(c.proceso, '') <> ''
            )
        )
    )"""


def _other_condition() -> str:
    return f"""(
        NOT {_paid_condition()}
        AND NOT {_critical_condition()}
        AND NOT {_sano_condition()}
    )"""


def _local_where(
    filters: CollectionFilters,
    *,
    company_id: int,
    collector: str | None,
    exact_account: str | None = None,
) -> tuple[str, dict[str, Any]]:
    conditions = [
        "c.id_emp_cuenta = :company_id",
        "c.cuenta IS NOT NULL",
        "c.cuenta <> ''",
    ]
    params: dict[str, Any] = {"company_id": company_id}

    if collector:
        conditions.append("c.agente_verificador = :collector")
        params["collector"] = collector

    if exact_account:
        conditions.append("c.cuenta = :exact_account")
        params["exact_account"] = exact_account
    elif filters.account:
        conditions.append("c.cuenta = :account")
        params["account"] = filters.account

    if filters.folio:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM bitacora_ventas bvf
                WHERE bvf.no_cuenta = c.cuenta
                  AND bvf.id_emp_bv = :company_id
                  AND TRIM(CAST(bvf.folio AS CHAR)) = :folio
            )"""
        )
        params["folio"] = filters.folio

    if filters.phone:
        customer_phone = _phone_sql(
            "CONCAT(COALESCE(cli.tel1, ''), ' ', COALESCE(cli.tel2, ''), ' ', COALESCE(cli.tel3, ''), ' ', COALESCE(cli.telefonodl, ''))"
        )
        sale_phone = _phone_sql(
            "CONCAT(COALESCE(bvp.tel_1, ''), ' ', COALESCE(bvp.tel_2, ''), ' ', COALESCE(bvp.tel_3, ''))"
        )
        conditions.append(
            f"""(
                EXISTS (
                    SELECT 1 FROM clientes cli
                    WHERE cli.cod_cliente = c.cod_cli
                      AND cli.id_emp_cli = :company_id
                      AND {customer_phone} LIKE :phone
                )
                OR EXISTS (
                    SELECT 1 FROM bitacora_ventas bvp
                    WHERE bvp.no_cuenta = c.cuenta
                      AND bvp.id_emp_bv = :company_id
                      AND {sale_phone} LIKE :phone
                )
            )"""
        )
        params["phone"] = _like(filters.phone)

    if filters.name:
        conditions.append(
            """(
                EXISTS (
                    SELECT 1 FROM clientes clin
                    WHERE clin.cod_cliente = c.cod_cli
                      AND clin.id_emp_cli = :company_id
                      AND LOWER(COALESCE(clin.nombre_completo, CONCAT(COALESCE(clin.Nombre, ''), ' ', COALESCE(clin.apellido_p, ''), ' ', COALESCE(clin.apellido_m, '')))) LIKE LOWER(:name)
                )
                OR EXISTS (
                    SELECT 1 FROM bitacora_ventas bvn
                    WHERE bvn.no_cuenta = c.cuenta
                      AND bvn.id_emp_bv = :company_id
                      AND LOWER(COALESCE(bvn.nombre_completo, '')) LIKE LOWER(:name)
                )
            )"""
        )
        params["name"] = _like(filters.name)

    if filters.date_from:
        conditions.append("DATE(COALESCE(c.fecha_venta, c.fecha_venta_domicilio)) >= :date_from")
        params["date_from"] = filters.date_from
    if filters.date_to:
        conditions.append("DATE(COALESCE(c.fecha_venta, c.fecha_venta_domicilio)) <= :date_to")
        params["date_to"] = filters.date_to
    if filters.status != "all":
        conditions.append(f"NOT {_cancelled_condition()}")
    if filters.overdue_only:
        conditions.append("(COALESCE(c.vencido, 0) > 0 OR COALESCE(c.atrasos, 0) > 0)")
    if filters.paid_only or filters.status == "pagado":
        conditions.append(_paid_condition())
    elif not filters.include_paid and filters.status != "all":
        conditions.append(f"NOT {_paid_condition()}")
    if filters.active_only:
        conditions.append(f"NOT {_paid_condition()} AND NOT {_cancelled_condition()}")
    if filters.status == "critico":
        conditions.append(f"NOT {_paid_condition()} AND {_critical_condition()}")
    elif filters.status == "sano":
        conditions.append(_sano_condition())
    elif filters.status == "otro":
        conditions.append(_other_condition())

    return " AND ".join(f"({condition})" for condition in conditions), params


def _collection_select_sql(where_sql: str, *, include_pagination: bool) -> str:
    pagination = "LIMIT :limit OFFSET :offset" if include_pagination else "LIMIT 1"
    return f"""
        SELECT
            c.id_cuenta,
            c.cuenta,
            c.cod_cli,
            c.producto,
            c.fecha_venta,
            c.fecha_venta_domicilio,
            c.pago_inicial,
            c.enganche,
            c.plazo,
            c.precio_contado,
            c.saldo,
            c.pagos_minimos,
            c.liquida,
            c.vencido,
            c.atrasos,
            c.moratorio,
            c.estatus,
            c.proceso,
            c.ultimo_pago,
            c.asesor,
            c.agente_verificador,
            c.observaciones,
            (
                SELECT bv.folio
                FROM bitacora_ventas bv
                WHERE bv.no_cuenta = c.cuenta
                  AND bv.id_emp_bv = :company_id
                ORDER BY bv.fecha_venta DESC, bv.id_venta_b DESC
                LIMIT 1
            ) AS folio,
            (
                SELECT bv.nombre_completo
                FROM bitacora_ventas bv
                WHERE bv.no_cuenta = c.cuenta
                  AND bv.id_emp_bv = :company_id
                ORDER BY bv.fecha_venta DESC, bv.id_venta_b DESC
                LIMIT 1
            ) AS sale_customer_name,
            (
                SELECT bv.tel_1
                FROM bitacora_ventas bv
                WHERE bv.no_cuenta = c.cuenta
                  AND bv.id_emp_bv = :company_id
                ORDER BY bv.fecha_venta DESC, bv.id_venta_b DESC
                LIMIT 1
            ) AS sale_phone_1,
            (
                SELECT bv.tel_2
                FROM bitacora_ventas bv
                WHERE bv.no_cuenta = c.cuenta
                  AND bv.id_emp_bv = :company_id
                ORDER BY bv.fecha_venta DESC, bv.id_venta_b DESC
                LIMIT 1
            ) AS sale_phone_2,
            (
                SELECT bv.tel_3
                FROM bitacora_ventas bv
                WHERE bv.no_cuenta = c.cuenta
                  AND bv.id_emp_bv = :company_id
                ORDER BY bv.fecha_venta DESC, bv.id_venta_b DESC
                LIMIT 1
            ) AS sale_phone_3,
            (
                SELECT cli.nombre_completo
                FROM clientes cli
                WHERE cli.cod_cliente = c.cod_cli
                  AND cli.id_emp_cli = :company_id
                ORDER BY cli.id_cliente DESC
                LIMIT 1
            ) AS customer_name,
            (
                SELECT cli.tel1
                FROM clientes cli
                WHERE cli.cod_cliente = c.cod_cli
                  AND cli.id_emp_cli = :company_id
                ORDER BY cli.id_cliente DESC
                LIMIT 1
            ) AS customer_phone_1,
            (
                SELECT cli.tel2
                FROM clientes cli
                WHERE cli.cod_cliente = c.cod_cli
                  AND cli.id_emp_cli = :company_id
                ORDER BY cli.id_cliente DESC
                LIMIT 1
            ) AS customer_phone_2,
            (
                SELECT cli.tel3
                FROM clientes cli
                WHERE cli.cod_cliente = c.cod_cli
                  AND cli.id_emp_cli = :company_id
                ORDER BY cli.id_cliente DESC
                LIMIT 1
            ) AS customer_phone_3,
            (
                SELECT cli.telefonodl
                FROM clientes cli
                WHERE cli.cod_cliente = c.cod_cli
                  AND cli.id_emp_cli = :company_id
                ORDER BY cli.id_cliente DESC
                LIMIT 1
            ) AS customer_phone_dl,
            (
                SELECT COALESCE(SUM(ec.cantidad), 0)
                FROM estados_cuenta ec
                WHERE ec.cuenta_e = c.cuenta
                  AND ec.id_emp_estado_cuenta = :company_id
            ) AS payments_sum,
            (
                SELECT COUNT(*)
                FROM estados_cuenta ec
                WHERE ec.cuenta_e = c.cuenta
                  AND ec.id_emp_estado_cuenta = :company_id
            ) AS payments_count,
            (
                SELECT MAX(ec.fecha_pago)
                FROM estados_cuenta ec
                WHERE ec.cuenta_e = c.cuenta
                  AND ec.id_emp_estado_cuenta = :company_id
            ) AS last_payment_at
        FROM cuentas c
        WHERE {where_sql}
        ORDER BY COALESCE(c.fecha_venta, c.fecha_venta_domicilio) DESC, c.id_cuenta DESC
        {pagination}
    """


def _local_list_collections(
    db: Session,
    user: Any,
    filters: CollectionFilters,
    *,
    collector: str | None,
) -> tuple[list[dict[str, Any]], int]:
    where_sql, params = _local_where(
        filters,
        company_id=int(user.empresa_id),
        collector=collector,
    )
    total = int(
        db.execute(
            text(f"SELECT COUNT(*) FROM cuentas c WHERE {where_sql}"),
            params,
        ).scalar()
        or 0
    )
    query_params = {**params, "limit": filters.limit, "offset": filters.offset}
    rows = db.execute(
        text(_collection_select_sql(where_sql, include_pagination=True)),
        query_params,
    ).mappings().all()
    items = [
        item
        for row in rows
        if (item := normalize_collection_record(row, source="local_fallback", bridge_status="fallback_local"))
    ]
    return items, total


def _local_collection_detail(
    db: Session,
    user: Any,
    no_cuenta: str,
    *,
    collector: str | None,
    include_payments: bool = True,
) -> dict[str, Any] | None:
    empty_filters = CollectionFilters(
        limit=1,
        status="all",
        include_paid=True,
        active_only=False,
    )
    where_sql, params = _local_where(
        empty_filters,
        company_id=int(user.empresa_id),
        collector=collector,
        exact_account=no_cuenta,
    )
    row = db.execute(
        text(_collection_select_sql(where_sql, include_pagination=False)),
        params,
    ).mappings().first()
    if not row:
        return None
    payments = _local_payments(db, user, no_cuenta) if include_payments else []
    return normalize_collection_record(
        row,
        payments=payments,
        source="local_fallback",
        bridge_status="fallback_local",
    )


def _local_payments(db: Session, user: Any, no_cuenta: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                id,
                cuenta_e,
                id_item,
                producto_s,
                concepto,
                metodo_pago,
                cantidad,
                fecha_pago,
                saldo,
                usuario
            FROM estados_cuenta
            WHERE cuenta_e = :account
              AND id_emp_estado_cuenta = :company_id
            ORDER BY fecha_pago DESC, id DESC
            LIMIT :limit
            """
        ),
        {
            "account": no_cuenta,
            "company_id": int(user.empresa_id),
            "limit": max(1, min(100, int(limit or 100))),
        },
    ).mappings().all()
    return [payment for row in rows if (payment := normalize_payment(row))]


def _local_collection_managers(
    db: Session,
    user: Any,
    *,
    search: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = [
        "c.id_emp_cuenta = :company_id",
        "c.agente_verificador IS NOT NULL",
        "TRIM(c.agente_verificador) <> ''",
    ]
    params: dict[str, Any] = {
        "company_id": int(user.empresa_id),
        "limit": max(1, min(200, int(limit or 100))),
    }
    if search:
        conditions.append("LOWER(TRIM(c.agente_verificador)) LIKE LOWER(:search)")
        params["search"] = _like(search)

    rows = db.execute(
        text(
            f"""
            SELECT
                TRIM(c.agente_verificador) AS gestor,
                COUNT(*) AS accounts_count
            FROM cuentas c
            WHERE {" AND ".join(f"({condition})" for condition in conditions)}
            GROUP BY TRIM(c.agente_verificador)
            ORDER BY TRIM(c.agente_verificador) ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [manager for row in rows if (manager := normalize_collection_manager(row))]


def _merge_collection(primary: dict[str, Any], fallback: dict[str, Any] | None) -> dict[str, Any]:
    if not fallback:
        return primary
    merged = dict(primary)
    for key, value in fallback.items():
        if key in {"customer", "financial_summary", "siga_bridge"}:
            continue
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value

    for nested_key in ("customer", "financial_summary"):
        nested = dict(fallback.get(nested_key) or {})
        nested.update({
            key: value
            for key, value in (primary.get(nested_key) or {}).items()
            if value not in (None, "", [], {})
        })
        merged[nested_key] = nested

    return merged


async def list_collection_managers(
    db: Session,
    user: Any,
    *,
    search: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if not can_filter_collections_by_gestor(user):
        return {
            "ok": True,
            "items": [],
            "meta": {
                "source": "none",
                "limit": 0,
                "warnings": ["gestor_catalog_not_allowed"],
            },
        }

    clean_search = _clean_manager_search(search)
    normalized_limit = max(1, min(200, int(limit or 100)))
    started_at = time.perf_counter()
    bridge_status = "disabled"
    bridge_error = None

    if settings.SIGA_BRIDGE_ENABLED:
        try:
            raw = await get_siga_bridge_client().get_collection_managers(
                int(user.empresa_id),
                search=clean_search,
                limit=normalized_limit,
            )
            managers = normalize_collection_managers(raw)
            logger.info(
                "collections_managers_bridge_loaded",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "has_search": bool(clean_search),
                    "limit": normalized_limit,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "rows_returned": len(managers),
                    "source": "bridge",
                },
            )
            return {
                "ok": True,
                "items": managers,
                "meta": {
                    "source": "bridge",
                    "limit": normalized_limit,
                    "warnings": [],
                    "source_field": "cuentas.agente_verificador",
                },
            }
        except SigaBridgeError as exc:
            bridge_status = "timeout" if exc.__class__.__name__ == "SigaBridgeUnavailableError" else "fallback_local"
            bridge_error = exc.__class__.__name__
            logger.warning(
                "collections_managers_bridge_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "has_search": bool(clean_search),
                    "error_type": bridge_error,
                    "status_code": getattr(exc, "status_code", None),
                },
            )

    managers = _local_collection_managers(db, user, search=clean_search, limit=normalized_limit)
    logger.info(
        "collections_managers_local_loaded",
        extra={
            "company_id": getattr(user, "empresa_id", None),
            "role": getattr(user, "role", None),
            "has_search": bool(clean_search),
            "limit": normalized_limit,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "rows_returned": len(managers),
            "source": "local_fallback",
        },
    )
    return {
        "ok": True,
        "items": managers,
        "meta": {
            "source": "local_fallback",
            "bridge_status": bridge_status,
            "bridge_error": bridge_error,
            "limit": normalized_limit,
            "warnings": [] if managers else ["gestor_catalog_empty"],
            "source_field": "cuentas.agente_verificador",
        },
    }


async def list_collections(
    db: Session,
    user: Any,
    filters: CollectionFilters,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    collector, warnings, has_scope = _authorized_collector(db, user, filters)
    if not has_scope:
        return _empty_response(
            filters,
            source="local_fallback",
            bridge_status="no_scope",
            warnings=warnings,
            collector=collector,
        )

    bridge_status = "disabled"
    bridge_error = None
    if settings.SIGA_BRIDGE_ENABLED:
        try:
            raw = await get_siga_bridge_client().get_collections(
                int(user.empresa_id),
                cuenta=filters.account,
                folio=filters.folio,
                phone=filters.phone,
                name=filters.name,
                status=filters.status,
                classification=filters.classification,
                date_from=filters.date_from,
                date_to=filters.date_to,
                overdue_only=filters.overdue_only,
                paid_only=filters.paid_only,
                include_paid=filters.include_paid,
                active_only=filters.active_only,
                collector=collector,
                gestor=collector,
                limit=filters.limit,
                offset=filters.offset,
            )
            payload = _as_mapping(raw)
            raw_items = payload.get("items") or payload.get("accounts") or payload.get("data") or []
            if isinstance(raw_items, list):
                items = [
                    item
                    for row in raw_items
                    if (item := normalize_collection_record(row, source="siga_bridge", bridge_status="ok"))
                ]
                if not filters.include_paid and filters.status != "pagado":
                    items = [item for item in items if not item.get("is_paid")]
                if filters.status in CLASSIFICATIONS:
                    items = [
                        item
                        for item in items
                        if item.get("classification") == filters.status
                    ]
                total = int(payload.get("total")) if payload.get("total") is not None else None
                bridge_warnings = warnings + [
                    str(warning)
                    for warning in (_as_mapping(payload.get("meta")).get("warnings") or [])
                    if warning
                ]
                response = _collections_response(
                    filters,
                    items=items,
                    total=total,
                    source="siga_bridge",
                    bridge_status="ok",
                    warnings=bridge_warnings,
                    collector=collector,
                    has_more=bool(payload.get("has_more")) if "has_more" in payload else None,
                    next_cursor=_safe_text(payload.get("next_cursor")),
                )
                logger.info(
                    "collections_list_loaded",
                    extra={
                        "company_id": getattr(user, "empresa_id", None),
                        "role": getattr(user, "role", None),
                        "source": "bridge",
                        "limit": filters.limit,
                        "offset": filters.offset,
                        "include_paid": filters.include_paid,
                        "active_only": filters.active_only,
                        "filters_applied": _filters_applied(filters, collector=collector),
                        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        "rows_returned": len(items),
                    },
                )
                return response
        except SigaBridgeError as exc:
            bridge_status = "timeout" if exc.__class__.__name__ == "SigaBridgeUnavailableError" else "fallback_local"
            bridge_error = exc.__class__.__name__
            logger.warning(
                "collections_bridge_list_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "error_type": bridge_error,
                    "status_code": getattr(exc, "status_code", None),
                },
            )
        except Exception:
            bridge_status = "fallback_local"
            bridge_error = "UnexpectedError"
            logger.exception(
                "collections_bridge_list_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                },
            )

    items, total = _local_list_collections(db, user, filters, collector=collector)
    response = _collections_response(
        filters,
        items=items,
        total=total,
        source="local_fallback",
        bridge_status=bridge_status,
        bridge_error=bridge_error,
        warnings=warnings,
        collector=collector,
    )
    logger.info(
        "collections_list_loaded",
        extra={
            "company_id": getattr(user, "empresa_id", None),
            "role": getattr(user, "role", None),
            "source": "local_fallback",
            "bridge_status": bridge_status,
            "limit": filters.limit,
            "offset": filters.offset,
            "include_paid": filters.include_paid,
            "active_only": filters.active_only,
            "filters_applied": _filters_applied(filters, collector=collector),
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "rows_returned": len(items),
        },
    )
    return response


async def get_collection_detail(
    db: Session,
    user: Any,
    no_cuenta: str,
    *,
    force_refresh: bool = False,
    include_paid: bool = False,
) -> dict[str, Any] | None:
    collector = _scoped_collector(db, user)
    if getattr(user, "role", None) == "cobranza" and not collector:
        return None

    local_item = _local_collection_detail(
        db,
        user,
        no_cuenta,
        collector=collector,
        include_payments=False,
    )
    if not local_item:
        return None
    if local_item.get("is_paid") and not include_paid:
        local_item["siga_bridge"] = {
            **(local_item.get("siga_bridge") or {}),
            "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
            "status": "paid_requires_filter",
            "source": "local_fallback",
            "available": False,
        }
        return local_item

    if not settings.SIGA_BRIDGE_ENABLED:
        local_item["payments"] = _local_payments(db, user, no_cuenta)
        return local_item

    try:
        client = get_siga_bridge_client()
        account_payload = await client.get_account(
            no_cuenta,
            int(user.empresa_id),
            bypass_cache=force_refresh,
        )
        payments_payload = await client.get_payments(
            no_cuenta,
            int(user.empresa_id),
            limit=100,
            bypass_cache=force_refresh,
        )
        account_data = _as_mapping(account_payload)
        payment_items = normalize_payments(payments_payload)
        bridge_item = normalize_collection_record(
            {
                **account_data,
                "payments": payment_items,
            },
            payments=payment_items,
            source="siga_bridge",
            bridge_status="ok",
        )
        if not bridge_item:
            return local_item
        return _merge_collection(bridge_item, local_item)
    except SigaBridgeError as exc:
        logger.warning(
            "collections_bridge_detail_failed",
            extra={
                "company_id": getattr(user, "empresa_id", None),
                "role": getattr(user, "role", None),
                "no_cuenta_masked": _mask(no_cuenta),
                "error_type": exc.__class__.__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
    except Exception:
        logger.exception(
            "collections_bridge_detail_unexpected",
            extra={
                "company_id": getattr(user, "empresa_id", None),
                "role": getattr(user, "role", None),
                "no_cuenta_masked": _mask(no_cuenta),
            },
        )

    local_item["payments"] = _local_payments(db, user, no_cuenta)
    local_item["payments_count"] = len(local_item["payments"])
    local_item["siga_bridge"] = {
        **(local_item.get("siga_bridge") or {}),
        "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
        "status": "fallback_local",
        "source": "local_fallback",
        "available": False,
    }
    return local_item


async def get_collection_payments(
    db: Session,
    user: Any,
    no_cuenta: str,
    *,
    include_paid: bool = False,
) -> list[dict[str, Any]] | None:
    collector = _scoped_collector(db, user)
    if getattr(user, "role", None) == "cobranza" and not collector:
        return None

    local_item = _local_collection_detail(
        db,
        user,
        no_cuenta,
        collector=collector,
        include_payments=False,
    )
    if not local_item:
        return None
    if local_item.get("is_paid") and not include_paid:
        return []
    if settings.SIGA_BRIDGE_ENABLED:
        try:
            payments_payload = await get_siga_bridge_client().get_payments(
                no_cuenta,
                int(user.empresa_id),
                limit=100,
            )
            payments = normalize_payments(payments_payload)
            if payments:
                return payments
        except SigaBridgeError as exc:
            logger.warning(
                "collections_bridge_payments_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                    "error_type": exc.__class__.__name__,
                    "status_code": getattr(exc, "status_code", None),
                },
            )
        except Exception:
            logger.exception(
                "collections_bridge_payments_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                },
            )
    return _local_payments(db, user, no_cuenta)


def _mask(value: Any, *, visible: int = 4) -> str | None:
    text_value = _safe_text(value)
    if text_value is None:
        return None
    if len(text_value) <= visible:
        return "***"
    return f"***{text_value[-visible:]}"
