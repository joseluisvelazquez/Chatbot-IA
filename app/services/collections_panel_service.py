from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import logging
import re
import time
import unicodedata
from typing import Any, Mapping

from sqlalchemy import bindparam, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import ChatSessions
from app.security.auth_service import get_nombre_resumido, restrict_to_assigned
from app.services.siga_bridge import SigaBridgeError, get_siga_bridge_client
from app.services.siga_bridge_sale import normalize_bridge_total_pagado
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


BRIDGE_LIST_PAYMENT_ENRICH_LIMIT = 100
BRIDGE_LIST_PAYMENT_ENRICH_CONCURRENCY = 4


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


def _address_text_from_mapping(address: Mapping[str, Any]) -> str | None:
    if not address:
        return None

    street = _first_text(address.get("street"), address.get("calle"))
    external = _first_text(
        address.get("external_number"),
        address.get("numero_exterior"),
        address.get("num_ext"),
    )
    internal = _first_text(
        address.get("internal_number"),
        address.get("numero_interior"),
        address.get("num_int"),
    )
    neighborhood = _first_text(address.get("neighborhood"), address.get("colonia"))
    city = _first_text(address.get("city"), address.get("ciudad"), address.get("municipio"))
    state = _first_text(address.get("state"), address.get("estado"))
    postal_code = _first_text(address.get("postal_code"), address.get("cp"), address.get("codigo_postal"))

    street_parts = [part for part in (street, external) if part]
    if internal:
        street_parts.append(f"Int {internal}")
    line_one = " ".join(street_parts)
    postal = f"CP {postal_code}" if postal_code else None
    parts = [part for part in (line_one, neighborhood, city, state, postal) if part]
    return ", ".join(parts) if parts else None


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

    amount = _first_money(
        payment.get("amount"),
        payment.get("cantidad"),
        payment.get("importe"),
        payment.get("monto"),
        payment.get("abono"),
        payment.get("pago"),
        payment.get("paid_amount"),
        payment.get("payment_amount"),
        payment.get("importe_pago"),
        payment.get("importe_abono"),
        payment.get("monto_pago"),
        payment.get("monto_abono"),
        payment.get("valor_pago"),
        payment.get("cantidad_pago"),
        payment.get("valor"),
    )
    status_text = _first_text(
        payment.get("status"),
        payment.get("estatus"),
        payment.get("estado"),
        payment.get("state"),
    )
    concept = _first_text(
        payment.get("concept"),
        payment.get("concepto"),
        payment.get("tipo"),
        payment.get("tipo_movimiento"),
        payment.get("movimiento"),
        payment.get("descripcion"),
    )

    return {
        "id": _first_text(payment.get("id")),
        "account": _first_text(payment.get("account"), payment.get("cuenta_e"), payment.get("cuenta"), payment.get("no_cuenta")),
        "concept": concept,
        "product": _first_text(payment.get("product"), payment.get("producto_s")),
        "payment_method": _first_text(payment.get("payment_method"), payment.get("metodo_pago")),
        "amount": amount,
        "paid_at": _first_date(
            payment.get("paid_at"),
            payment.get("fecha_pago"),
            payment.get("fecha"),
            payment.get("created_at"),
            payment.get("fecha_registro"),
            payment.get("fecha_cobro"),
            payment.get("fecha_movimiento"),
            payment.get("fecha_abono"),
        ),
        "balance_after_payment": _first_money(
            payment.get("balance_after_payment"),
            payment.get("saldo_despues"),
            payment.get("saldo_restante"),
            payment.get("saldo"),
        ),
        "user": _first_text(payment.get("user"), payment.get("usuario")),
        "status": status_text,
        "cancelled": bool(
            _truthy_active(payment.get("cancelled")) is True
            or _truthy_active(payment.get("canceled")) is True
            or _truthy_active(payment.get("cancelado")) is True
            or _truthy_active(payment.get("devolucion")) is True
            or _truthy_active(payment.get("refund")) is True
            or _truthy_active(payment.get("refunded")) is True
        ),
    }


def _payment_records_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return []

    for key in (
        "payments",
        "pagos",
        "historial_pagos",
        "payment_history",
        "history",
        "movimientos",
        "estado_cuenta",
        "estados_cuenta",
        "transactions",
        "records",
        "rows",
        "items",
        "recent_payments",
        "abonos",
        "data",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            nested = _payment_records_from_payload(value)
            if nested:
                return nested
    return []


def _has_payment_records_payload(payload: Any) -> bool:
    if isinstance(payload, list):
        return True
    if not isinstance(payload, Mapping):
        return False

    for key in (
        "payments",
        "pagos",
        "historial_pagos",
        "payment_history",
        "history",
        "movimientos",
        "estado_cuenta",
        "estados_cuenta",
        "transactions",
        "records",
        "rows",
        "items",
        "recent_payments",
        "abonos",
        "data",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return True
        if isinstance(value, Mapping) and _has_payment_records_payload(value):
            return True
    return False


def _payment_is_excluded(payment: dict[str, Any]) -> bool:
    if payment.get("cancelled"):
        return True
    marker = _strip_accents(
        " ".join(
            value.lower()
            for value in (
                _first_text(payment.get("status")),
                _first_text(payment.get("concept")),
            )
            if value
        )
    )
    return any(token in marker for token in ("cancel", "anulad", "devol", "refund", "revers"))


def _same_date_prefix(left: Any, right: Any) -> bool:
    left_text = _safe_text(left)
    right_text = _safe_text(right)
    if not left_text or not right_text:
        return False
    return left_text[:10] == right_text[:10]


def _payment_matches_initial_payment(payment: dict[str, Any], initial_payment: Any, sale_date: Any) -> bool:
    initial_amount = _safe_decimal(initial_payment)
    payment_amount = _safe_decimal(payment.get("amount"))
    if initial_amount is None or payment_amount is None or payment_amount != initial_amount:
        return False

    marker = _strip_accents(
        " ".join(
            value.lower()
            for value in (
                _first_text(payment.get("id")),
                _first_text(payment.get("concept")),
                _first_text(payment.get("product")),
                _first_text(payment.get("payment_method")),
            )
            if value
        )
    )
    if any(token in marker for token in ("inicial", "enganche", "anticipo", "down payment")):
        return True
    return _same_date_prefix(payment.get("paid_at"), sale_date)


def _with_initial_payment(
    payments: list[dict[str, Any]],
    *,
    no_cuenta: str,
    initial_payment: Any,
    sale_date: Any,
    product: Any = None,
) -> list[dict[str, Any]]:
    amount = _first_money(initial_payment)
    amount_value = _safe_decimal(amount)
    if amount_value is None or amount_value <= 0:
        return payments
    if any(_payment_matches_initial_payment(payment, amount, sale_date) for payment in payments):
        return payments

    return [
        *payments,
        {
            "id": "initial_payment",
            "account": no_cuenta,
            "concept": "Pago inicial",
            "product": _first_text(product),
            "payment_method": None,
            "amount": amount,
            "paid_at": _first_date(sale_date),
            "balance_after_payment": None,
            "user": None,
            "status": "APLICADO",
            "cancelled": False,
            "source": "initial_payment",
        },
    ]


def _sum_normalized_payments(payments: list[dict[str, Any]]) -> tuple[str | None, int]:
    total = Decimal("0")
    counted = 0
    for payment in payments:
        amount = _safe_decimal(payment.get("amount"))
        if amount is None or amount <= 0 or _payment_is_excluded(payment):
            continue
        total += amount
        counted += 1
    return (_money(total) if counted else None, counted)


def normalize_payments(payload: Any) -> list[dict[str, Any]]:
    raw_items = _payment_records_from_payload(payload)
    payments: list[dict[str, Any]] = []
    for item in raw_items:
        payment = normalize_payment(item)
        if not payment:
            continue
        amount = _safe_decimal(payment.get("amount"))
        if amount is None or amount <= 0 or _payment_is_excluded(payment):
            continue
        payments.append(payment)
    return payments


def normalize_collection_record(
    record: Any,
    *,
    payments: list[dict[str, Any]] | None = None,
    source: str = "siga_bridge",
    bridge_status: str = "ok",
    prefer_payment_total: bool | None = None,
) -> dict[str, Any] | None:
    item = _as_mapping(record)
    if not item:
        return None

    account_raw = item.get("account")
    account = _as_mapping(account_raw)
    customer = _as_mapping(item.get("customer"))
    customer_address = _as_mapping(customer.get("address"))
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
    folio = _first_text(item.get("folio"), sale.get("folio"))
    product = _first_text(item.get("product"), account.get("product"), account.get("producto"), sale.get("descripcion"))
    sale_date = _first_date(
        item.get("sale_date"),
        item.get("fecha_venta"),
        item.get("fecha_relevante"),
        account.get("sale_date"),
        account.get("fecha_venta"),
        sale.get("fecha_venta"),
    )
    has_initial_payment_row = any(
        _payment_matches_initial_payment(payment, initial_payment, sale_date)
        for payment in payment_items
    )
    payment_items = _with_initial_payment(
        payment_items,
        no_cuenta=no_cuenta,
        initial_payment=initial_payment,
        sale_date=sale_date,
        product=product,
    )
    total_paid_source = None
    bridge_total_info: dict[str, Any] = {}
    prefer_bridge_payments = (
        payments is not None and _has_payment_records_payload(item)
        if prefer_payment_total is None
        else bool(prefer_payment_total)
    )
    if source == "siga_bridge":
        bridge_total_info = normalize_bridge_total_pagado(
            dict(item),
            folio=folio,
            no_cuenta=no_cuenta,
            prefer_payments=prefer_bridge_payments,
        )
        total_paid = _first_money(bridge_total_info.get("total_pagado"))
        total_paid_source = _first_text(bridge_total_info.get("total_pagado_source"))
    else:
        total_paid = _first_money(
            item.get("total_paid"),
            item.get("total_pagado"),
            summary.get("paid_total"),
            summary.get("total_paid"),
            summary.get("total_pagado"),
            summary.get("total_abonado"),
            summary.get("abonos_total"),
        )

    if total_paid is None and source != "siga_bridge":
        payments_sum_raw = summary.get("payments_sum") if summary else None
        if payments_sum_raw is None:
            payments_sum_raw = item.get("payments_sum")
        if payments_sum_raw is not None:
            payments_sum = _safe_decimal(payments_sum_raw) or Decimal("0")
            initial = _safe_decimal(initial_payment) or Decimal("0")
            initial_extra = initial if initial > 0 and not has_initial_payment_row else Decimal("0")
            total_paid = _money(payments_sum + initial_extra)
            total_paid_source = (
                "local.payments_sum+initial_payment"
                if initial_extra > 0
                else "local.payments_sum"
            )

    payment_items_total, counted_payment_items = _sum_normalized_payments(payment_items)
    can_use_payment_items_total = (
        source != "siga_bridge"
        or payments is not None
        or _has_payment_records_payload(item)
    )
    if prefer_bridge_payments and counted_payment_items:
        total_paid = payment_items_total
        total_paid_source = "payments.sum"
    elif total_paid is None and counted_payment_items and can_use_payment_items_total:
        total_paid = payment_items_total
        total_paid_source = total_paid_source or "payments.sum"

    payments_count = _first_number(
        len(payment_items) if payments is not None and payment_items else None,
        item.get("payments_count"),
        summary.get("payments_count"),
        bridge_total_info.get("payments_count"),
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
        "folio": folio,
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
                item.get("domicilio"),
                item.get("direccion"),
                customer.get("address_text"),
                customer.get("domicilio"),
                customer.get("direccion"),
                customer_address.get("full"),
                _address_text_from_mapping(customer_address),
            ),
        },
        "account_status": status,
        "process": process,
        "classification": classification,
        "estado_calculado": classification,
        "classification_label": classification_label,
        "product": product,
        "sale_date": sale_date,
        "last_payment": last_payment,
        "balance": balance,
        "debt": _first_money(item.get("debt"), balance),
        "overdue_amount": overdue_amount,
        "days_overdue": days_overdue,
        "total_paid": total_paid,
        "total_pagado": total_paid,
        "total_paid_source": total_paid_source,
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
            "total_pagado": total_paid,
            "total_paid_source": total_paid_source,
            "payments_count": int(payments_count or 0),
        },
        "payments": payment_items,
        "siga_url": build_siga_account_url(no_cuenta, folio),
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


def _manager_key(value: Any) -> str | None:
    text_value = _safe_text(value)
    if not text_value:
        return None
    return _strip_accents(text_value).casefold()


def _truthy_active(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return int(value) == 1

    text_value = _strip_accents(str(value).strip().lower())
    if not text_value:
        return None
    if text_value in {"1", "activo", "activa", "alta", "enabled", "habilitado", "habilitada", "true", "si", "yes"}:
        return True
    if text_value in {"0", "inactivo", "inactiva", "baja", "disabled", "deshabilitado", "deshabilitada", "false", "no"}:
        return False
    if any(token in text_value for token in ("baja", "inactiv", "deshabil", "deleted")):
        return False
    if "activ" in text_value or "habilit" in text_value:
        return True
    return None


def _manager_is_active(item: Mapping[str, Any]) -> bool:
    for key in ("deleted_at", "fecha_baja", "baja", "disabled_at"):
        value = item.get(key)
        if value not in (None, "", 0, "0", False):
            return False

    for key in ("activo", "active", "is_active", "enabled", "habilitado", "estatus", "status"):
        active = _truthy_active(item.get(key))
        if active is not None:
            return active

    return True


def _manager_has_collection_role(item: Mapping[str, Any]) -> bool:
    role_values = [
        _first_text(item.get("puesto"), item.get("position")),
        _first_text(item.get("role"), item.get("rol")),
        _first_text(item.get("tipo")),
    ]
    present_values = [value for value in role_values if value]
    if not present_values:
        return True

    role_text = _strip_accents(" ".join(present_values).lower())
    return (
        "cobranza" in role_text
        or "gestor" in role_text
        or "collector" in role_text
    )


def normalize_collection_manager(record: Any) -> dict[str, Any] | None:
    item = _as_mapping(record)
    if not item:
        return None

    if not _manager_is_active(item) or not _manager_has_collection_role(item):
        return None

    value = _first_text(
        item.get("value"),
        item.get("gestor"),
        item.get("collector"),
        item.get("nombre_resumido"),
    )
    if not value:
        return None
    label = _first_text(item.get("label"), item.get("nombre"), item.get("nombre_completo"), value)
    return {
        "id": _first_text(item.get("id"), item.get("gestor_id"), item.get("id_colaborador")),
        "value": value,
        "label": label,
        "nombre": label,
        "usuario": _first_text(item.get("usuario"), item.get("username"), item.get("nombre_usuario")),
        "activo": True,
        "empresa_id": _first_number(item.get("empresa_id"), item.get("id_emp_col"), item.get("id_emp")),
        "accounts_count": _first_number(item.get("accounts_count")),
        "source": _first_text(item.get("source"), "siga_bridge"),
        "source_field": _first_text(item.get("source_field"), "colaboradores.nombre_resumido"),
    }


def normalize_collection_managers(
    payload: Any,
    *,
    allowed_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    data = _as_mapping(payload)
    raw_items = data.get("items") or data.get("data") or data.get("managers") or []
    if not isinstance(raw_items, list):
        return []
    managers_by_key: dict[str, dict[str, Any]] = {}
    for row in raw_items:
        manager = normalize_collection_manager(row)
        if not manager:
            continue
        key = _manager_key(manager.get("value"))
        if not key or (allowed_keys is not None and key not in allowed_keys):
            continue
        if key in managers_by_key:
            existing_count = _safe_decimal(managers_by_key[key].get("accounts_count")) or Decimal("0")
            next_count = _safe_decimal(manager.get("accounts_count")) or Decimal("0")
            managers_by_key[key]["accounts_count"] = int(max(existing_count, next_count))
            continue
        managers_by_key[key] = manager
    return list(managers_by_key.values())


def _manager_key_set(managers: list[dict[str, Any]]) -> set[str]:
    return {
        key
        for manager in managers
        if (key := _manager_key(manager.get("value")))
    }


def _normalize_phone_match(value: Any) -> str | None:
    text_value = _safe_text(value)
    if not text_value:
        return None
    digits = re.sub(r"\D+", "", text_value)
    if len(digits) >= 10:
        return digits[-10:]
    return None


def _phone_match_variants(phone: str) -> set[str]:
    normalized = _normalize_phone_match(phone)
    if not normalized:
        return set()
    return {
        normalized,
        f"52{normalized}",
        f"521{normalized}",
        f"+52{normalized}",
        f"+521{normalized}",
    }


def _read_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _path_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _extract_session_accounts(extra_json: Any) -> set[str]:
    payload = _read_json_payload(extra_json)
    paths = (
        ("no_cuenta",),
        ("cuenta",),
        ("account_number",),
        ("account", "no_cuenta"),
        ("account", "cuenta"),
        ("account", "account_number"),
        ("siga_bridge", "normalized", "no_cuenta"),
        ("siga_bridge", "verification_cache", "snapshot", "no_cuenta"),
        ("siga_bridge", "verification_lookup", "data", "no_cuenta"),
        ("siga_bridge", "verification_lookup", "data", "account", "no_cuenta"),
        ("siga_bridge", "verification_lookup", "data", "account", "cuenta"),
        ("siga_bridge", "customer_lookup", "data", "no_cuenta"),
        ("siga_bridge", "customer_lookup", "data", "account", "no_cuenta"),
        ("siga_bridge", "customer_lookup", "data", "account", "cuenta"),
    )
    accounts = {
        account
        for path in paths
        if (account := _first_text(_path_value(payload, path)))
    }
    return accounts


def _conversation_sort_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text_value = _safe_text(value)
    if not text_value:
        return datetime.min
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _conversation_candidate(row: Any) -> dict[str, Any] | None:
    get_value = row.get if isinstance(row, Mapping) else lambda key, default=None: getattr(row, key, default)
    session_id = get_value("id")
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return None
    extra_json = get_value("extra_json")
    return {
        "id": session_id,
        "folio": _first_text(get_value("folio")),
        "phone": _first_text(get_value("phone")),
        "phone_match": _normalize_phone_match(get_value("phone")),
        "accounts": _extract_session_accounts(extra_json),
        "last_message_at": get_value("last_message_at"),
        "updated_at": get_value("updated_at"),
        "created_at": get_value("created_at"),
    }


def _conversation_rank(candidate: dict[str, Any]) -> datetime:
    return max(
        _conversation_sort_value(candidate.get("last_message_at")),
        _conversation_sort_value(candidate.get("updated_at")),
        _conversation_sort_value(candidate.get("created_at")),
    )


def _set_no_conversation(item: dict[str, Any]) -> dict[str, Any]:
    item["has_conversation"] = False
    item["conversation_session_id"] = None
    item["conversation_url"] = None
    return item


def _set_conversation(item: dict[str, Any], candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not candidate:
        return _set_no_conversation(item)
    session_id = int(candidate["id"])
    item["has_conversation"] = True
    item["conversation_session_id"] = str(session_id)
    item["conversation_url"] = f"/panel/?view=conversations&session_id={session_id}"
    return item


def _account_json_condition() -> str:
    paths = (
        "$.no_cuenta",
        "$.cuenta",
        "$.account_number",
        "$.account.no_cuenta",
        "$.account.cuenta",
        "$.account.account_number",
        "$.siga_bridge.normalized.no_cuenta",
        "$.siga_bridge.verification_cache.snapshot.no_cuenta",
        "$.siga_bridge.verification_lookup.data.no_cuenta",
        "$.siga_bridge.verification_lookup.data.account.no_cuenta",
        "$.siga_bridge.verification_lookup.data.account.cuenta",
        "$.siga_bridge.customer_lookup.data.no_cuenta",
        "$.siga_bridge.customer_lookup.data.account.no_cuenta",
        "$.siga_bridge.customer_lookup.data.account.cuenta",
    )
    return " OR ".join(
        f"JSON_UNQUOTE(JSON_EXTRACT(extra_json, '{path}')) IN :accounts"
        for path in paths
    )


def _conversation_candidates(db: Session, user: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if db is None or not items:
        return []

    session_ids: set[int] = set()
    folios: set[str] = set()
    phone_variants: set[str] = set()
    accounts: set[str] = set()
    for item in items:
        if item.get("session_id"):
            try:
                session_ids.add(int(item["session_id"]))
            except (TypeError, ValueError):
                pass
        if folio := _first_text(item.get("folio")):
            folios.add(folio)
        for phone in [item.get("phone"), *(item.get("phones") if isinstance(item.get("phones"), list) else [])]:
            phone_variants.update(_phone_match_variants(phone))
        if account := _first_text(item.get("no_cuenta")):
            accounts.add(account)

    candidates_by_id: dict[int, dict[str, Any]] = {}
    conditions = []
    if session_ids:
        conditions.append(ChatSessions.id.in_(session_ids))
    if folios:
        conditions.append(ChatSessions.folio.in_(folios))
    if phone_variants:
        conditions.append(ChatSessions.phone.in_(phone_variants))

    if conditions:
        try:
            query = restrict_to_assigned(db.query(ChatSessions), user, db)
            rows = (
                query
                .filter(or_(*conditions))
                .order_by(ChatSessions.last_message_at.desc(), ChatSessions.updated_at.desc())
                .limit(300)
                .all()
            )
            for row in rows:
                candidate = _conversation_candidate(row)
                if candidate:
                    candidates_by_id[candidate["id"]] = candidate
        except SQLAlchemyError as exc:
            logger.warning(
                "collections_conversation_candidates_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "error_type": exc.__class__.__name__,
                    "source": "session_lookup",
                },
            )

    if accounts:
        try:
            sql = text(
                f"""
                SELECT id, phone, folio, extra_json, last_message_at, updated_at, created_at
                FROM chat_sessions
                WHERE ({_account_json_condition()})
                ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC
                LIMIT :limit
                """
            ).bindparams(bindparam("accounts", expanding=True))
            rows = db.execute(
                sql,
                {
                    "accounts": sorted(accounts),
                    "limit": 300,
                },
            ).mappings().all()
            for row in rows:
                candidate = _conversation_candidate(row)
                if candidate:
                    candidates_by_id[candidate["id"]] = candidate
        except SQLAlchemyError as exc:
            logger.warning(
                "collections_conversation_candidates_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "error_type": exc.__class__.__name__,
                    "source": "account_json_lookup",
                },
            )

    return sorted(candidates_by_id.values(), key=_conversation_rank, reverse=True)


def attach_conversation_links(
    db: Session,
    user: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        return items

    for item in items:
        _set_no_conversation(item)

    candidates = sorted(_conversation_candidates(db, user, items), key=_conversation_rank, reverse=True)
    if not candidates:
        return items

    by_id: dict[int, dict[str, Any]] = {}
    by_folio: dict[str, dict[str, Any]] = {}
    by_phone: dict[str, dict[str, Any]] = {}
    by_account: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        by_id.setdefault(int(candidate["id"]), candidate)
        if candidate.get("folio"):
            by_folio.setdefault(str(candidate["folio"]), candidate)
        if candidate.get("phone_match"):
            by_phone.setdefault(str(candidate["phone_match"]), candidate)
        for account in candidate.get("accounts") or set():
            by_account.setdefault(str(account), candidate)

    for item in items:
        selected = None
        if item.get("session_id"):
            try:
                selected = by_id.get(int(item["session_id"]))
            except (TypeError, ValueError):
                selected = None
        if selected is None and item.get("folio"):
            selected = by_folio.get(str(item["folio"]))
        if selected is None:
            item_phones = [item.get("phone"), *(item.get("phones") if isinstance(item.get("phones"), list) else [])]
            for phone in item_phones:
                normalized = _normalize_phone_match(phone)
                if normalized and by_phone.get(normalized):
                    selected = by_phone[normalized]
                    break
        if selected is None and item.get("no_cuenta"):
            selected = by_account.get(str(item["no_cuenta"]))

        _set_conversation(item, selected)

    return items


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


def _local_payments_with_initial(
    db: Session,
    user: Any,
    no_cuenta: str,
    local_item: dict[str, Any],
) -> list[dict[str, Any]]:
    local_summary = local_item.get("financial_summary") if isinstance(local_item.get("financial_summary"), dict) else {}
    return _with_initial_payment(
        _local_payments(db, user, no_cuenta),
        no_cuenta=no_cuenta,
        initial_payment=local_summary.get("initial_payment"),
        sale_date=local_item.get("sale_date"),
        product=local_item.get("product"),
    )


def _local_payment_summaries_for_accounts(
    db: Session,
    user: Any,
    accounts: list[str],
) -> dict[str, dict[str, Any]]:
    account_values = [account for account in dict.fromkeys(accounts) if account]
    if not account_values:
        return {}

    valid_payment_sql = """
        COALESCE(ec.cantidad, 0) > 0
        AND LOWER(COALESCE(ec.concepto, '')) NOT LIKE '%cancel%'
        AND LOWER(COALESCE(ec.concepto, '')) NOT LIKE '%anulad%'
        AND LOWER(COALESCE(ec.concepto, '')) NOT LIKE '%devol%'
        AND LOWER(COALESCE(ec.concepto, '')) NOT LIKE '%revers%'
    """
    initial_marker_sql = """
        (
            LOWER(COALESCE(ec.concepto, '')) LIKE '%inicial%'
            OR LOWER(COALESCE(ec.concepto, '')) LIKE '%enganche%'
            OR LOWER(COALESCE(ec.producto_s, '')) LIKE '%inicial%'
            OR LOWER(COALESCE(ec.producto_s, '')) LIKE '%enganche%'
        )
    """
    sql = text(
        f"""
        SELECT
            c.cuenta AS no_cuenta,
            COALESCE(NULLIF(c.pago_inicial, 0), NULLIF(c.enganche, 0), 0) AS initial_payment,
            COALESCE(c.fecha_venta, c.fecha_venta_domicilio) AS sale_date,
            COALESCE(SUM(CASE WHEN {valid_payment_sql} THEN ec.cantidad ELSE 0 END), 0) AS payments_sum,
            COALESCE(SUM(CASE WHEN {valid_payment_sql} THEN 1 ELSE 0 END), 0) AS payments_count,
            COALESCE(SUM(
                CASE
                    WHEN {valid_payment_sql}
                     AND {initial_marker_sql}
                     AND ABS(COALESCE(ec.cantidad, 0) - COALESCE(NULLIF(c.pago_inicial, 0), NULLIF(c.enganche, 0), 0)) < 0.01
                    THEN 1
                    ELSE 0
                END
            ), 0) AS initial_payment_rows,
            MAX(CASE WHEN {valid_payment_sql} THEN ec.fecha_pago ELSE NULL END) AS last_payment_at
        FROM cuentas c
        LEFT JOIN estados_cuenta ec
          ON ec.cuenta_e = c.cuenta
         AND ec.id_emp_estado_cuenta = :company_id
        WHERE c.id_emp_cuenta = :company_id
          AND c.cuenta IN :accounts
        GROUP BY
            c.cuenta,
            c.pago_inicial,
            c.enganche,
            c.fecha_venta,
            c.fecha_venta_domicilio
        """
    ).bindparams(bindparam("accounts", expanding=True))
    rows = db.execute(
        sql,
        {
            "company_id": int(user.empresa_id),
            "accounts": account_values,
        },
    ).mappings().all()

    summaries: dict[str, dict[str, Any]] = {}
    for row in rows:
        account = _first_text(row.get("no_cuenta"))
        if not account:
            continue
        payments_sum = _safe_decimal(row.get("payments_sum")) or Decimal("0")
        initial_payment = _safe_decimal(row.get("initial_payment")) or Decimal("0")
        initial_rows = int(_safe_decimal(row.get("initial_payment_rows")) or Decimal("0"))
        total = payments_sum
        source = "local.payments_sum"
        extra_initial = Decimal("0")
        if initial_payment > 0 and initial_rows <= 0:
            extra_initial = initial_payment
            total += initial_payment
            source = "local.payments_sum+initial_payment"

        summaries[account] = {
            "total_paid": _money(total),
            "total_paid_source": source,
            "payments_sum": _money(payments_sum),
            "initial_payment": _money(initial_payment) if initial_payment > 0 else None,
            "payments_count": int(_safe_decimal(row.get("payments_count")) or Decimal("0")) + (1 if extra_initial > 0 else 0),
            "last_payment": _first_date(row.get("last_payment_at"), row.get("sale_date") if extra_initial > 0 else None),
        }
    return summaries


def _enrich_collection_list_with_local_payment_summary(
    db: Session,
    user: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if db is None or not items:
        return items

    accounts = [
        account
        for item in items
        if (account := _first_text(item.get("no_cuenta")))
    ]
    try:
        summaries = _local_payment_summaries_for_accounts(db, user, accounts)
    except SQLAlchemyError as exc:
        logger.warning(
            "collections_local_payment_summary_failed",
            extra={
                "company_id": getattr(user, "empresa_id", None),
                "role": getattr(user, "role", None),
                "error_type": exc.__class__.__name__,
            },
        )
        return items

    for item in items:
        summary = summaries.get(str(item.get("no_cuenta")))
        if not summary:
            continue
        if item.get("total_paid") in (None, "", "-", "0", "0.00") and summary.get("total_paid") is not None:
            item["total_paid"] = summary["total_paid"]
            item["total_pagado"] = summary["total_paid"]
            item["total_paid_source"] = summary["total_paid_source"]
            financial_summary = dict(item.get("financial_summary") or {})
            financial_summary["total_paid"] = summary["total_paid"]
            financial_summary["total_pagado"] = summary["total_paid"]
            financial_summary["total_paid_source"] = summary["total_paid_source"]
            if not financial_summary.get("initial_payment") and summary.get("initial_payment"):
                financial_summary["initial_payment"] = summary["initial_payment"]
            item["financial_summary"] = financial_summary
        if not item.get("payments_count") and summary.get("payments_count") is not None:
            item["payments_count"] = summary["payments_count"]
            financial_summary = dict(item.get("financial_summary") or {})
            financial_summary["payments_count"] = summary["payments_count"]
            item["financial_summary"] = financial_summary
        if not item.get("last_payment") and summary.get("last_payment"):
            item["last_payment"] = summary["last_payment"]
    return items


def _payment_summary_from_payload(payload: Any) -> Mapping[str, Any]:
    data = _as_mapping(payload)
    return _as_mapping(
        data.get("summary")
        or data.get("payment_summary")
        or data.get("payment")
        or data.get("financial_summary")
    )


def _collection_records_from_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        raw_items = payload
    else:
        data = _as_mapping(payload)
        raw_items = data.get("items") or data.get("accounts") or data.get("data") or []

    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _collection_record_for_account(payload: Any, no_cuenta: str) -> Mapping[str, Any]:
    records = _collection_records_from_payload(payload)
    if not records:
        return {}

    expected = str(no_cuenta)
    for record in records:
        candidate = _first_text(
            record.get("no_cuenta"),
            record.get("account_number"),
            record.get("cuenta"),
            record.get("account"),
        )
        if candidate and str(candidate) == expected:
            return record
    return records[0]


async def _enrich_one_collection_with_bridge_payment_summary(
    client: Any,
    user: Any,
    item: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> None:
    no_cuenta = _first_text(item.get("no_cuenta"))
    if not no_cuenta:
        return
    if item.get("total_paid") not in (None, "", "-", "0"):
        return

    async with semaphore:
        try:
            payload = await client.get_payments(
                no_cuenta,
                int(user.empresa_id),
                limit=BRIDGE_LIST_PAYMENT_ENRICH_LIMIT,
            )
        except SigaBridgeError as exc:
            logger.warning(
                "collections_bridge_payment_summary_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                    "error_type": exc.__class__.__name__,
                    "status_code": getattr(exc, "status_code", None),
                },
            )
            return
        except Exception:
            logger.exception(
                "collections_bridge_payment_summary_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                },
            )
            return

    total_info = normalize_bridge_total_pagado(
        _as_mapping(payload),
        folio=item.get("folio"),
        no_cuenta=no_cuenta,
        prefer_payments=False,
    )
    total_paid = _first_money(total_info.get("total_pagado"))
    summary = _payment_summary_from_payload(payload)
    payments = normalize_payments(payload)
    initial_payment = _first_money(
        summary.get("initial_payment"),
        summary.get("pago_inicial"),
        summary.get("enganche"),
    )
    payments_with_initial = _with_initial_payment(
        payments,
        no_cuenta=no_cuenta,
        initial_payment=initial_payment,
        sale_date=item.get("sale_date"),
        product=item.get("product"),
    )

    if total_paid is None:
        total_paid, _counted = _sum_normalized_payments(payments_with_initial)

    if total_paid is None:
        return

    item["total_paid"] = total_paid
    item["total_pagado"] = total_paid
    item["total_paid_source"] = _first_text(total_info.get("total_pagado_source"), "bridge.payments")
    financial_summary = dict(item.get("financial_summary") or {})
    financial_summary["total_paid"] = total_paid
    financial_summary["total_pagado"] = total_paid
    financial_summary["total_paid_source"] = item["total_paid_source"]
    if initial_payment and not financial_summary.get("initial_payment"):
        financial_summary["initial_payment"] = initial_payment
    item["financial_summary"] = financial_summary

    summary_count = _first_number(
        summary.get("payments_count"),
        summary.get("count"),
        total_info.get("payments_count"),
    )
    rows_count = len(payments_with_initial) if payments_with_initial else None
    count_candidates = [value for value in (summary_count, rows_count) if value is not None]
    count_value = max(count_candidates) if count_candidates else None
    if count_value is not None:
        item["payments_count"] = int(count_value)
        financial_summary["payments_count"] = int(count_value)


async def enrich_collection_list_with_bridge_payment_summary(
    client: Any,
    user: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = [
        item
        for item in items
        if item.get("total_paid") in (None, "", "-", "0") and _first_text(item.get("no_cuenta"))
    ]
    if not targets:
        return items

    semaphore = asyncio.Semaphore(BRIDGE_LIST_PAYMENT_ENRICH_CONCURRENCY)
    await asyncio.gather(
        *(
            _enrich_one_collection_with_bridge_payment_summary(client, user, item, semaphore)
            for item in targets
        )
    )
    return items


def _local_collection_managers(
    db: Session,
    user: Any,
    *,
    search: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = [
        "col.id_emp_col = :company_id",
        "COALESCE(col.estatus, 0) = 1",
        "col.nombre_resumido IS NOT NULL",
        "TRIM(col.nombre_resumido) <> ''",
        """(
            LOWER(COALESCE(col.puesto, '')) LIKE '%cobranza%'
            OR LOWER(COALESCE(col.puesto, '')) LIKE '%gestor%'
        )""",
    ]
    params: dict[str, Any] = {
        "company_id": int(user.empresa_id),
        "limit": max(1, min(200, int(limit or 100))),
    }
    if search:
        conditions.append(
            """(
                LOWER(TRIM(col.nombre_resumido)) LIKE LOWER(:search)
                OR LOWER(COALESCE(col.nombre_usuario, '')) LIKE LOWER(:search)
                OR LOWER(COALESCE(col.nombre_completo, '')) LIKE LOWER(:search)
            )"""
        )
        params["search"] = _like(search)

    rows = db.execute(
        text(
            f"""
            SELECT
                col.id AS id,
                TRIM(col.nombre_resumido) AS gestor,
                col.nombre_resumido,
                col.nombre_usuario,
                col.nombre_completo,
                col.puesto,
                col.estatus,
                col.id_emp_col,
                COUNT(DISTINCT c.cuenta) AS accounts_count,
                'local_colaboradores' AS source,
                'colaboradores.nombre_resumido' AS source_field
            FROM colaboradores col
            LEFT JOIN cuentas c
              ON TRIM(c.agente_verificador) = TRIM(col.nombre_resumido)
             AND c.id_emp_cuenta = col.id_emp_col
            WHERE {" AND ".join(f"({condition})" for condition in conditions)}
            GROUP BY
                col.id,
                col.nombre_resumido,
                col.nombre_usuario,
                col.nombre_completo,
                col.puesto,
                col.estatus,
                col.id_emp_col
            ORDER BY TRIM(col.nombre_resumido) ASC
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
    active_local_managers: list[dict[str, Any]] | None = None
    active_manager_keys: set[str] | None = None

    if db is not None:
        try:
            active_local_managers = _local_collection_managers(
                db,
                user,
                search=clean_search,
                limit=normalized_limit,
            )
            active_manager_keys = _manager_key_set(active_local_managers)
        except SQLAlchemyError as exc:
            logger.warning(
                "collections_managers_active_catalog_failed",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "error_type": exc.__class__.__name__,
                },
            )

    if settings.SIGA_BRIDGE_ENABLED:
        try:
            raw = await get_siga_bridge_client().get_collection_managers(
                int(user.empresa_id),
                search=clean_search,
                limit=normalized_limit,
            )
            managers = normalize_collection_managers(raw, allowed_keys=active_manager_keys)
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
                    "source_field": "colaboradores.nombre_resumido",
                    "active_filter": "colaboradores.estatus=1; puesto contains cobranza/gestor; id_emp_col=current_company",
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

    managers = active_local_managers
    if managers is None:
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
            "source_field": "colaboradores.nombre_resumido",
            "active_filter": "colaboradores.estatus=1; puesto contains cobranza/gestor; id_emp_col=current_company",
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
            bridge_client = get_siga_bridge_client()
            raw = await bridge_client.get_collections(
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
                items = await enrich_collection_list_with_bridge_payment_summary(bridge_client, user, items)
                items = _enrich_collection_list_with_local_payment_summary(db, user, items)
                items = attach_conversation_links(db, user, items)
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
    items = attach_conversation_links(db, user, items)
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
    if local_item and local_item.get("is_paid") and not include_paid:
        local_item["siga_bridge"] = {
            **(local_item.get("siga_bridge") or {}),
            "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
            "status": "paid_detail_loaded",
            "source": "local_fallback",
            "available": False,
        }

    if not settings.SIGA_BRIDGE_ENABLED:
        if not local_item:
            return None
        local_item["payments"] = _local_payments_with_initial(db, user, no_cuenta, local_item)
        local_item["payments_count"] = len(local_item["payments"])
        return attach_conversation_links(db, user, [local_item])[0]

    try:
        client = get_siga_bridge_client()
        collection_record: Mapping[str, Any] = {}
        try:
            collection_payload = await client.get_collections(
                int(user.empresa_id),
                cuenta=no_cuenta,
                include_paid=True,
                active_only=False,
                limit=1,
                bypass_cache=force_refresh,
            )
            collection_record = _collection_record_for_account(collection_payload, no_cuenta)
        except SigaBridgeError as exc:
            logger.warning(
                "collections_bridge_detail_context_failed",
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
                "collections_bridge_detail_context_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                },
            )
        account_payload: Any = {}
        try:
            account_payload = await client.get_account(
                no_cuenta,
                int(user.empresa_id),
                bypass_cache=force_refresh,
            )
        except SigaBridgeError as exc:
            logger.warning(
                "collections_bridge_detail_account_failed",
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
                "collections_bridge_detail_account_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                },
            )
        payments_payload: Any = {}
        try:
            payments_payload = await client.get_payments(
                no_cuenta,
                int(user.empresa_id),
                limit=100,
                bypass_cache=force_refresh,
            )
        except SigaBridgeError as exc:
            logger.warning(
                "collections_bridge_detail_payments_failed",
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
                "collections_bridge_detail_payments_unexpected",
                extra={
                    "company_id": getattr(user, "empresa_id", None),
                    "role": getattr(user, "role", None),
                    "no_cuenta_masked": _mask(no_cuenta),
                },
            )
        account_data = _as_mapping(account_payload)
        payment_data = _as_mapping(payments_payload)
        payment_payload_has_list = _has_payment_records_payload(payments_payload)
        raw_payment_items = _payment_records_from_payload(payments_payload)
        payment_items = normalize_payments(payments_payload)
        if not payment_items and local_item:
            payment_items = _local_payments(db, user, no_cuenta)
        local_summary = (
            local_item.get("financial_summary")
            if local_item and isinstance(local_item.get("financial_summary"), dict)
            else {}
        )
        if not collection_record and not account_data and not payment_data:
            if not local_item:
                return None
            local_item["payments"] = _local_payments_with_initial(db, user, no_cuenta, local_item)
            local_item["payments_count"] = len(local_item["payments"])
            return attach_conversation_links(db, user, [local_item])[0]
        account_object = _as_mapping(account_data.get("account"))
        account_record = {
            **collection_record,
            **account_data,
            **payment_data,
            "payments": raw_payment_items,
            "no_cuenta": no_cuenta,
        }
        if account_object:
            account_record["account"] = account_object
        if not _first_text(
            account_record.get("initial_payment"),
            account_record.get("pago_inicial"),
            _as_mapping(account_record.get("account")).get("initial_payment"),
            _as_mapping(account_record.get("payment_summary")).get("initial_payment"),
        ) and local_summary.get("initial_payment"):
            account_record["initial_payment"] = local_summary.get("initial_payment")
        if not _first_text(account_record.get("sale_date"), account_record.get("fecha_venta")) and local_item and local_item.get("sale_date"):
            account_record["sale_date"] = local_item.get("sale_date")
        if not _first_text(account_record.get("product"), _as_mapping(account_record.get("account")).get("product")) and local_item and local_item.get("product"):
            account_record["product"] = local_item.get("product")
        bridge_item = normalize_collection_record(
            account_record,
            payments=payment_items,
            source="siga_bridge",
            bridge_status="ok",
            prefer_payment_total=bool(payment_payload_has_list or payment_items),
        )
        if not bridge_item:
            if not local_item:
                return None
            local_item["payments"] = _local_payments_with_initial(db, user, no_cuenta, local_item)
            local_item["payments_count"] = len(local_item["payments"])
            return attach_conversation_links(db, user, [local_item])[0]
        return attach_conversation_links(db, user, [_merge_collection(bridge_item, local_item)])[0]
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

    if not local_item:
        return None
    local_item["payments"] = _local_payments_with_initial(db, user, no_cuenta, local_item)
    local_item["payments_count"] = len(local_item["payments"])
    local_item["siga_bridge"] = {
        **(local_item.get("siga_bridge") or {}),
        "enabled": bool(settings.SIGA_BRIDGE_ENABLED),
        "status": "fallback_local",
        "source": "local_fallback",
        "available": False,
    }
    return attach_conversation_links(db, user, [local_item])[0]


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
    local_summary = (
        local_item.get("financial_summary")
        if local_item and isinstance(local_item.get("financial_summary"), dict)
        else {}
    )
    if settings.SIGA_BRIDGE_ENABLED:
        try:
            payments_payload = await get_siga_bridge_client().get_payments(
                no_cuenta,
                int(user.empresa_id),
                limit=100,
            )
            payments = normalize_payments(payments_payload)
            summary = _payment_summary_from_payload(payments_payload)
            initial_payment = _first_money(
                local_summary.get("initial_payment"),
                summary.get("initial_payment"),
                summary.get("pago_inicial"),
                summary.get("enganche"),
            )
            sale_date = local_item.get("sale_date") if local_item else None
            product = local_item.get("product") if local_item else None
            payments = _with_initial_payment(
                payments,
                no_cuenta=no_cuenta,
                initial_payment=initial_payment,
                sale_date=sale_date,
                product=product,
            )
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
    if not local_item:
        return None
    return _with_initial_payment(
        _local_payments(db, user, no_cuenta),
        no_cuenta=no_cuenta,
        initial_payment=local_summary.get("initial_payment"),
        sale_date=local_item.get("sale_date"),
        product=local_item.get("product"),
    )


def _mask(value: Any, *, visible: int = 4) -> str | None:
    text_value = _safe_text(value)
    if text_value is None:
        return None
    if len(text_value) <= visible:
        return "***"
    return f"***{text_value[-visible:]}"
