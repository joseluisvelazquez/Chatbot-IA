from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.adapters.whatsapp_client import send_template_message
from app.config.settings import settings
from app.db.models import PaymentReminder
from app.services.collections_panel_service import (
    normalize_collection_record,
    normalize_payments,
    resolve_collection_payment_state,
)
from app.services.siga_bridge import SigaBridgeError, get_siga_bridge_client
from app.utils.account_reference import format_account_reference, resolve_payment_account_reference
from app.utils.timezone import mexico_now_naive


logger = logging.getLogger(__name__)

PAYMENT_STATUS_PAID = "pagado"
PAYMENT_STATUS_UNPAID = "no_pagado"
PAYMENT_STATUS_UNKNOWN = "unknown"
PAYMENT_STATUS_SOURCE_UNKNOWN = "unknown"

STATUS_SCHEDULED = "scheduled"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_CANCELLED = "cancelled"
STATUS_CANCELLED_SETTLED = "cancelled_settled"
STATUS_FAILED = "failed"

CLASS_NOT_DUE = "not_due"
CLASS_DUE_TODAY_UNPAID = "due_today_no_pagado"
CLASS_OVERDUE_UNPAID = "overdue_no_pagado"
CLASS_SETTLED = "settled"
CLASS_INSUFFICIENT_BRIDGE_DATA = "insufficient_bridge_data"
CLASS_BRIDGE_ERROR = "bridge_error"
CLASS_ALREADY_SCHEDULED = "already_scheduled"
CLASS_ALREADY_SENT = "already_sent"
CLASS_SKIPPED_TEST_PHONE_ONLY = "skipped_test_phone_only"

REMINDER_PAYMENT_PENDING = "payment_pending"
REMINDER_PAYMENT_OVERDUE = "payment_overdue"
REMINDER_NEXT_PAYMENT = "next_payment"

ACTIVE_REMINDER_STATUSES = {
    STATUS_SCHEDULED,
}

WEEKDAYS = {
    "monday": 0,
    "lunes": 0,
    "tuesday": 1,
    "martes": 1,
    "wednesday": 2,
    "miercoles": 2,
    "thursday": 3,
    "jueves": 3,
    "friday": 4,
    "viernes": 4,
    "saturday": 5,
    "sabado": 5,
    "sunday": 6,
    "domingo": 6,
}


@dataclass(slots=True)
class PaymentSchedule:
    due_date: date
    next_due_date: date
    weekday: int | None
    source: str
    base_date: date | None = None
    base_date_source: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None


class PaymentScheduleError(ValueError):
    pass


@dataclass(slots=True)
class BridgeAccountSnapshot:
    bridge_found: bool
    company_id: int
    cuenta: str | None = None
    folio: str | None = None
    phone: str | None = None
    customer_name: str | None = None
    customer_code: str | None = None
    sale_date: date | None = None
    product: str | None = None
    balance: Decimal | None = None
    minimum_payment: Decimal | None = None
    account_status: str | None = None
    process: str | None = None
    is_paid: bool = False
    is_active: bool = True
    has_overdue: bool = False
    payment_base_date: date | None = None
    payment_base_source: str | None = None
    next_payment_date: date | None = None
    payment_weekday: int | None = None
    payment_source: str = "calculated_sale_date"
    payment_status: str = PAYMENT_STATUS_UNKNOWN
    payment_status_source: str = PAYMENT_STATUS_SOURCE_UNKNOWN
    payment_status_reason: str | None = None
    account_reference_raw: str | None = None
    account_reference_formatted: str | None = None
    account_reference_prefix: str | None = None
    account_reference_source: str | None = None
    account_reference_valid: bool = False
    account_reference_reason: str | None = None
    raw_item: dict[str, Any] | None = None
    missing_fields: list[str] | None = None
    error_code: str | None = None
    error_message_sanitized: str | None = None

    @property
    def snapshot_hash(self) -> str | None:
        if not self.raw_item:
            return None
        body = json.dumps(self.raw_item, sort_keys=True, default=str, ensure_ascii=True)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @property
    def settled(self) -> bool:
        return self.payment_status == PAYMENT_STATUS_PAID


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    )


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mask(value: Any, *, visible: int = 4) -> str | None:
    text = str(value or "")
    if not text:
        return None
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def normalize_phone_for_whatsapp(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 10:
        return f"521{digits}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"521{digits[-10:]}"
    if len(digits) >= 13 and digits.startswith("521"):
        return digits
    return digits


def is_valid_whatsapp_phone(value: Any) -> bool:
    phone = normalize_phone_for_whatsapp(value)
    return bool(phone and phone.isdigit() and 12 <= len(phone) <= 15)


# TEMPORARY TEST_PHONE_ONLY GATE - remove this block when production sends are approved.
def is_test_phone_allowed(phone: Any) -> bool:
    allowed = {
        normalized
        for raw in (settings.TEST_PHONE_ONLY or [])
        if (normalized := normalize_phone_for_whatsapp(raw))
    }
    normalized_phone = normalize_phone_for_whatsapp(phone)
    return bool(allowed and normalized_phone in allowed)


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text or text in {"-", "N/A", "null", "None"}:
        return None
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "N/D"
    return f"${value:,.2f}"


def _date_text(value: date | None) -> str:
    if not value:
        return "N/D"
    return value.strftime("%d/%m/%Y")


def _safe_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    iso_candidate = text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(iso_candidate, "%Y-%m-%d").date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _weekday_from_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    text = _strip_accents(str(value).strip().lower())
    if not text:
        return None
    if text.isdigit():
        numeric = int(text)
        if 0 <= numeric <= 6:
            return numeric
        if 1 <= numeric <= 7:
            return numeric - 1
    return WEEKDAYS.get(text)


def _current_weekly_due(base_due_date: date, today: date) -> date:
    if today < base_due_date:
        return base_due_date
    cycles = (today - base_due_date).days // 7
    return base_due_date + timedelta(days=cycles * 7)


def _current_or_next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def calculate_due_schedule(
    *,
    sale_date: date | None = None,
    today: date,
    payment_base_date: date | None = None,
    bridge_next_payment_date: date | None = None,
    bridge_weekday: int | None = None,
    default_weekday: str | None = None,
    allow_default_weekday_fallback: bool = False,
) -> PaymentSchedule:
    del bridge_weekday

    if bridge_next_payment_date:
        due_date = _current_weekly_due(bridge_next_payment_date, today)
        return PaymentSchedule(
            due_date=due_date,
            next_due_date=due_date + timedelta(days=7),
            weekday=bridge_next_payment_date.weekday(),
            source="bridge_next_payment_date",
            base_date=bridge_next_payment_date,
            base_date_source="bridge_next_payment_date",
        )

    if payment_base_date:
        base_due = payment_base_date
        due_date = _current_weekly_due(base_due, today)
        return PaymentSchedule(
            due_date=due_date,
            next_due_date=due_date + timedelta(days=7),
            weekday=base_due.weekday(),
            source="bridge_payment_base_date",
            base_date=payment_base_date,
            base_date_source="bridge_payment_base_date",
        )

    if sale_date:
        base_due = sale_date + timedelta(days=7)
        due_date = _current_weekly_due(base_due, today)
        return PaymentSchedule(
            due_date=due_date,
            next_due_date=due_date + timedelta(days=7),
            weekday=base_due.weekday(),
            source="bridge_fecha_venta_plus_7",
            base_date=sale_date,
            base_date_source="bridge_fecha_venta",
        )

    if allow_default_weekday_fallback and default_weekday:
        weekday = _weekday_from_value(default_weekday)
        if weekday is None:
            raise PaymentScheduleError("invalid_default_weekday")
        due_date = _current_or_next_weekday(today, weekday)
        return PaymentSchedule(
            due_date=due_date,
            next_due_date=due_date + timedelta(days=7),
            weekday=weekday,
            source="env_default_weekday_fallback",
            base_date=None,
            base_date_source=None,
            fallback_used=True,
            fallback_reason="missing_bridge_payment_base_date",
        )

    raise PaymentScheduleError("missing_bridge_payment_base_date")


def calculate_snapshot_due_schedule(
    snapshot: BridgeAccountSnapshot,
    *,
    today: date,
) -> PaymentSchedule:
    return calculate_due_schedule(
        sale_date=snapshot.sale_date,
        today=today,
        payment_base_date=snapshot.payment_base_date,
        bridge_next_payment_date=snapshot.next_payment_date,
        bridge_weekday=snapshot.payment_weekday,
        default_weekday=settings.PAYMENT_REMINDER_DEFAULT_WEEKDAY,
        allow_default_weekday_fallback=bool(settings.PAYMENT_REMINDER_DEFAULT_WEEKDAY),
    )


def classify_reminder_case(
    *,
    bridge_error: bool = False,
    bridge_found: bool = True,
    missing_fields: list[str] | None = None,
    payment_status: str = PAYMENT_STATUS_UNPAID,
    due_date: date | None = None,
    today: date | None = None,
) -> str:
    if bridge_error:
        return CLASS_BRIDGE_ERROR
    if not bridge_found or missing_fields:
        return CLASS_INSUFFICIENT_BRIDGE_DATA
    if payment_status == PAYMENT_STATUS_PAID:
        return CLASS_SETTLED
    if not due_date or not today:
        return CLASS_INSUFFICIENT_BRIDGE_DATA
    if today < due_date:
        return CLASS_NOT_DUE

    return CLASS_DUE_TODAY_UNPAID if today == due_date else CLASS_OVERDUE_UNPAID


def _scheduled_datetime(due_date: date) -> datetime:
    hour = min(max(int(settings.PAYMENT_REMINDER_SEND_HOUR or 10), 0), 23)
    return datetime.combine(due_date, time(hour=hour))


def _collection_records_from_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = payload.get("items") or payload.get("accounts") or payload.get("data") or []
    else:
        raw_items = []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _deep_first(data: Any, keys: set[str]) -> Any:
    if isinstance(data, Mapping):
        for key, value in data.items():
            if str(key) in keys and value not in (None, "", [], {}):
                return value
        for value in data.values():
            found = _deep_first(value, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(data, list):
        for item in data:
            found = _deep_first(item, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def _merge_record(
    collection_record: Mapping[str, Any] | None,
    account_payload: Any,
    payments_payload: Any,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(collection_record or {})
    if isinstance(account_payload, list):
        account_payload = next((item for item in account_payload if isinstance(item, Mapping)), None)
    if isinstance(account_payload, Mapping):
        for key, value in account_payload.items():
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
        if "account" not in merged:
            merged["account"] = account_payload.get("account") or account_payload
    if payments_payload is not None:
        merged["payments"] = normalize_payments(payments_payload)
    return merged


def _snapshot_from_item(
    item: dict[str, Any] | None,
    *,
    company_id: int,
    fallback_cuenta: str | None = None,
    fallback_folio: str | None = None,
) -> BridgeAccountSnapshot:
    if not item:
        return BridgeAccountSnapshot(
            bridge_found=False,
            company_id=company_id,
            cuenta=fallback_cuenta,
            folio=fallback_folio,
            missing_fields=["account"],
        )

    financial = item.get("financial_summary") if isinstance(item.get("financial_summary"), Mapping) else {}
    customer = item.get("customer") if isinstance(item.get("customer"), Mapping) else {}
    raw = dict(item)
    raw.pop("payments", None)

    phone = normalize_phone_for_whatsapp(item.get("phone"))
    if not phone:
        phones = item.get("phones") if isinstance(item.get("phones"), list) else []
        phone = normalize_phone_for_whatsapp(phones[0]) if phones else None

    next_payment_date = _safe_date(
        _deep_first(
            item,
            {
                "next_payment_date",
                "fecha_proximo_pago",
                "fecha_proxima_pago",
                "proxima_fecha_pago",
                "fecha_vencimiento",
                "due_date",
            },
        )
    )
    payment_base_date = _safe_date(
        _deep_first(
            item,
            {
                "payment_base_date",
                "fecha_base_pago",
                "fecha_inicial_pago",
                "first_payment_date",
                "fecha_primer_pago",
                "fecha_inicio_pagos",
            },
        )
    )
    payment_weekday = _weekday_from_value(
        _deep_first(
            item,
            {
                "payment_weekday",
                "payment_day",
                "dia_pago",
                "dia_de_pago",
                "weekday",
                "day_of_payment",
            },
        )
    )
    payment_state = resolve_collection_payment_state(item)
    account_reference = resolve_payment_account_reference(
        item,
        raw_account=item.get("no_cuenta") or fallback_cuenta,
    )

    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=company_id,
        cuenta=_clean_text(item.get("no_cuenta") or fallback_cuenta),
        folio=_clean_text(item.get("folio") or fallback_folio),
        phone=phone,
        customer_name=_clean_text(item.get("customer_name") or customer.get("name")),
        customer_code=_clean_text(customer.get("customer_code")),
        sale_date=_safe_date(item.get("sale_date")),
        product=_clean_text(item.get("product")),
        balance=_safe_decimal(item.get("balance") or financial.get("balance")),
        minimum_payment=_safe_decimal(financial.get("minimum_payment")),
        account_status=_clean_text(item.get("account_status")),
        process=_clean_text(item.get("process")),
        is_paid=bool(item.get("is_paid")),
        is_active=bool(item.get("is_active", True)),
        has_overdue=bool(item.get("has_overdue")),
        payment_base_date=payment_base_date,
        payment_base_source="bridge_payment_base_date" if payment_base_date else None,
        next_payment_date=next_payment_date,
        payment_weekday=payment_weekday,
        payment_source=(
            "bridge_next_payment_date"
            if next_payment_date
            else "bridge_payment_base_date"
            if payment_base_date
            else "bridge_fecha_venta"
            if _safe_date(item.get("sale_date"))
            else "missing_bridge_payment_base_date"
        ),
        payment_status=str(payment_state.get("estado_pago") or PAYMENT_STATUS_UNKNOWN),
        payment_status_source=str(payment_state.get("fuente_estado_pago") or PAYMENT_STATUS_SOURCE_UNKNOWN),
        payment_status_reason=_clean_text(payment_state.get("reason")),
        account_reference_raw=account_reference.raw,
        account_reference_formatted=account_reference.formatted,
        account_reference_prefix=account_reference.prefix,
        account_reference_source=account_reference.source,
        account_reference_valid=account_reference.valid,
        account_reference_reason=account_reference.reason,
        raw_item=raw,
    )
    if account_reference.conflict:
        logger.warning(
            "payment_reminder_account_reference_mismatch",
            extra={
                "cuenta_masked": _mask(snapshot.cuenta),
                "folio_masked": _mask(snapshot.folio),
                "reference_source": account_reference.source,
                "conflict_reason": account_reference.conflict_reason,
            },
        )
    snapshot.missing_fields = required_snapshot_missing_fields(snapshot)
    return snapshot


def _preserve_payment_schedule_fields(
    normalized: dict[str, Any] | None,
    raw: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not normalized or not raw:
        return normalized
    normalized["_schedule_raw"] = dict(raw)
    for key in (
        "next_payment_date",
        "fecha_proximo_pago",
        "fecha_proxima_pago",
        "proxima_fecha_pago",
        "fecha_vencimiento",
        "due_date",
        "payment_base_date",
        "fecha_base_pago",
        "fecha_inicial_pago",
        "first_payment_date",
        "fecha_primer_pago",
        "fecha_inicio_pagos",
        "payment_weekday",
        "payment_day",
        "dia_pago",
        "dia_de_pago",
        "weekday",
        "day_of_payment",
    ):
        if key in raw and normalized.get(key) in (None, "", [], {}):
            normalized[key] = raw[key]
    return normalized


def required_snapshot_missing_fields(snapshot: BridgeAccountSnapshot) -> list[str]:
    missing: list[str] = []
    if not snapshot.cuenta:
        missing.append("cuenta")
    if not snapshot.account_reference_valid or not snapshot.account_reference_formatted:
        missing.append("cuenta_formateada")
    if not is_valid_whatsapp_phone(snapshot.phone):
        missing.append("phone")
    if not snapshot.customer_name:
        missing.append("customer_name")
    if snapshot.balance is None:
        missing.append("saldo")
    if snapshot.minimum_payment is None or snapshot.minimum_payment <= Decimal("0"):
        missing.append("monto_minimo")
    return missing


async def fetch_bridge_account_snapshot(
    *,
    cuenta: str | None,
    folio: str | None,
    company_id: int,
    client: Any | None = None,
) -> BridgeAccountSnapshot:
    client = client or get_siga_bridge_client()
    collection_record: Mapping[str, Any] | None = None
    account_payload: Any = None
    payments_payload: Any = None

    try:
        collection_payload = await client.get_collections(
            company_id,
            cuenta=cuenta,
            folio=folio,
            include_paid=True,
            active_only=False,
            limit=1,
            bypass_cache=True,
        )
        records = _collection_records_from_payload(collection_payload)
        collection_record = records[0] if records else None

        normalized_probe = normalize_collection_record(
            collection_record,
            source="siga_bridge",
            bridge_status="ok",
        ) if collection_record else None
        resolved_cuenta = cuenta or (normalized_probe or {}).get("no_cuenta")
        if resolved_cuenta:
            account_payload = await client.get_account(
                str(resolved_cuenta),
                company_id,
                bypass_cache=True,
            )
            payments_payload = await client.get_payments(
                str(resolved_cuenta),
                company_id,
                limit=100,
                bypass_cache=True,
            )

        merged = _merge_record(collection_record, account_payload, payments_payload)
        if resolved_cuenta and merged.get("no_cuenta") in (None, ""):
            merged["no_cuenta"] = resolved_cuenta
        normalized = normalize_collection_record(
            merged,
            payments=normalize_payments(payments_payload),
            source="siga_bridge",
            bridge_status="ok",
            prefer_payment_total=True,
        )
        normalized = _preserve_payment_schedule_fields(normalized, merged)
        snapshot = _snapshot_from_item(
            normalized,
            company_id=company_id,
            fallback_cuenta=resolved_cuenta,
            fallback_folio=folio,
        )
        logger.info(
            "payment_reminder_bridge_lookup",
            extra={
                "company_id": company_id,
                "cuenta_masked": _mask(snapshot.cuenta),
                "folio_masked": _mask(snapshot.folio),
                "bridge_found": snapshot.bridge_found,
                "account_reference_source": snapshot.account_reference_source,
                "account_reference_valid": snapshot.account_reference_valid,
                "missing_fields": snapshot.missing_fields or [],
            },
        )
        return snapshot
    except SigaBridgeError as exc:
        logger.warning(
            "payment_reminder_bridge_error",
            extra={
                "company_id": company_id,
                "cuenta_masked": _mask(cuenta),
                "folio_masked": _mask(folio),
                "error_type": exc.__class__.__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
        return BridgeAccountSnapshot(
            bridge_found=False,
            company_id=company_id,
            cuenta=cuenta,
            folio=folio,
            missing_fields=["bridge_error"],
            error_code="bridge_error",
            error_message_sanitized=exc.__class__.__name__,
        )


def _template_for_classification(classification: str) -> tuple[str | None, str | None]:
    if classification == CLASS_DUE_TODAY_UNPAID:
        return settings.META_PAYMENT_PENDING_TEMPLATE_NAME, REMINDER_PAYMENT_PENDING
    if classification == CLASS_OVERDUE_UNPAID:
        return (
            settings.META_PAYMENT_OVERDUE_TEMPLATE_NAME or settings.META_PAYMENT_PENDING_TEMPLATE_NAME,
            REMINDER_PAYMENT_OVERDUE if settings.META_PAYMENT_OVERDUE_TEMPLATE_NAME else REMINDER_PAYMENT_PENDING,
        )
    return None, None


def build_template_parameters(
    *,
    reminder_type: str,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule,
) -> list[str]:
    name = snapshot.customer_name or "cliente"
    cuenta = snapshot.account_reference_formatted or format_account_reference(snapshot.cuenta) or "N/D"
    minimum = _money_text(snapshot.minimum_payment)
    balance = _money_text(snapshot.balance)
    due_date = _date_text(schedule.due_date)
    next_due = _date_text(schedule.next_due_date)

    if reminder_type in {REMINDER_PAYMENT_PENDING, REMINDER_PAYMENT_OVERDUE}:
        return [name, cuenta, minimum, due_date, balance, "subir tu comprobante"]
    if reminder_type == REMINDER_NEXT_PAYMENT:
        return [name, cuenta, next_due, minimum, balance]
    return [name, cuenta]


def _response_meta_message_id(response: Any) -> str | None:
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    messages = payload.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[0], Mapping):
        return _clean_text(messages[0].get("id"))
    return None


def _existing_reminder(
    db: Session,
    *,
    cuenta: str,
    due_date: date,
    reminder_type: str,
) -> PaymentReminder | None:
    return (
        db.query(PaymentReminder)
        .filter(PaymentReminder.cuenta == cuenta)
        .filter(PaymentReminder.due_date == due_date)
        .filter(PaymentReminder.reminder_type == reminder_type)
        .first()
    )


def _update_reminder_from_snapshot(
    reminder: PaymentReminder,
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule,
    template_name: str | None,
) -> None:
    reminder.phone = snapshot.phone or reminder.phone
    reminder.folio = snapshot.folio or reminder.folio
    reminder.cuenta = snapshot.cuenta or reminder.cuenta
    reminder.due_date = schedule.due_date
    reminder.next_due_date = schedule.next_due_date
    reminder.scheduled_for = _scheduled_datetime(schedule.due_date)
    reminder.template_name = template_name
    reminder.saldo_snapshot = snapshot.balance
    reminder.monto_minimo_snapshot = snapshot.minimum_payment
    reminder.bridge_found = snapshot.bridge_found
    reminder.bridge_snapshot_hash = snapshot.snapshot_hash
    reminder.updated_at = mexico_now_naive()


def upsert_scheduled_reminder(
    db: Session,
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule,
    reminder_type: str,
    template_name: str | None,
    dry_run: bool = False,
) -> tuple[PaymentReminder | None, str]:
    if not snapshot.cuenta or not snapshot.phone:
        return None, CLASS_INSUFFICIENT_BRIDGE_DATA
    existing = _existing_reminder(
        db,
        cuenta=snapshot.cuenta,
        due_date=schedule.due_date,
        reminder_type=reminder_type,
    )
    if existing and existing.status == STATUS_SENT:
        return existing, CLASS_ALREADY_SENT
    if existing and existing.status in ACTIVE_REMINDER_STATUSES:
        if not dry_run:
            _update_reminder_from_snapshot(
                existing,
                snapshot=snapshot,
                schedule=schedule,
                template_name=template_name,
            )
            existing.status = STATUS_SCHEDULED
        return existing, CLASS_ALREADY_SCHEDULED
    if dry_run:
        return existing, "would_schedule"

    if existing:
        _update_reminder_from_snapshot(
            existing,
            snapshot=snapshot,
            schedule=schedule,
            template_name=template_name,
        )
        existing.status = STATUS_SCHEDULED
        existing.error_code = None
        existing.error_message_sanitized = None
        return existing, STATUS_SCHEDULED

    reminder = PaymentReminder(
        phone=snapshot.phone,
        folio=snapshot.folio,
        cuenta=snapshot.cuenta,
        due_date=schedule.due_date,
        next_due_date=schedule.next_due_date,
        scheduled_for=_scheduled_datetime(schedule.due_date),
        reminder_type=reminder_type,
        template_name=template_name,
        status=STATUS_SCHEDULED,
        saldo_snapshot=snapshot.balance,
        monto_minimo_snapshot=snapshot.minimum_payment,
        bridge_found=snapshot.bridge_found,
        bridge_snapshot_hash=snapshot.snapshot_hash,
        dry_run=False,
    )
    db.add(reminder)
    return reminder, STATUS_SCHEDULED


def _mark_result(
    reminder: PaymentReminder,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    now: datetime | None = None,
) -> None:
    now = now or mexico_now_naive()
    reminder.status = status
    reminder.error_code = error_code
    reminder.error_message_sanitized = error_message[:255] if error_message else None
    reminder.updated_at = now
    if status == STATUS_SENT:
        reminder.sent_at = now
    elif status in {STATUS_CANCELLED, STATUS_CANCELLED_SETTLED}:
        reminder.cancelled_at = now


def _cancel_future_settled(db: Session, *, cuenta: str, current_id: int | None = None) -> int:
    query = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.cuenta == cuenta)
        .filter(PaymentReminder.status.in_(list(ACTIVE_REMINDER_STATUSES)))
    )
    if current_id:
        query = query.filter(PaymentReminder.id != current_id)
    now = mexico_now_naive()
    return query.update(
        {
            PaymentReminder.status: STATUS_CANCELLED_SETTLED,
            PaymentReminder.cancelled_at: now,
            PaymentReminder.updated_at: now,
            PaymentReminder.error_code: None,
            PaymentReminder.error_message_sanitized: None,
        },
        synchronize_session=False,
    )


def _build_process_result(
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule | None,
    classification: str,
    template_name: str | None,
    reminder_type: str | None,
    dry_run: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    cuenta_formateada = snapshot.account_reference_formatted or format_account_reference(snapshot.cuenta)
    cuenta_formateada_valida = bool(
        (snapshot.account_reference_valid and snapshot.account_reference_formatted)
        or (cuenta_formateada and not snapshot.account_reference_reason)
    )
    should_send = bool(
        template_name
        and snapshot.payment_status == PAYMENT_STATUS_UNPAID
        and cuenta_formateada_valida
        and classification not in {CLASS_NOT_DUE, CLASS_SETTLED, CLASS_BRIDGE_ERROR, CLASS_INSUFFICIENT_BRIDGE_DATA}
    )
    return {
        "cuenta": snapshot.cuenta,
        "cuenta_raw": snapshot.account_reference_raw or snapshot.cuenta,
        "cuenta_formateada": cuenta_formateada,
        "prefijo_cuenta": snapshot.account_reference_prefix,
        "fuente_formato_cuenta": snapshot.account_reference_source,
        "cuenta_formateada_valida": cuenta_formateada_valida,
        "cuenta_formateada_reason": snapshot.account_reference_reason,
        "phone_masked": _mask(snapshot.phone),
        "saldo_actual": str(snapshot.balance) if snapshot.balance is not None else None,
        "fecha_base": schedule.base_date.isoformat() if schedule and schedule.base_date else None,
        "fecha_base_source": schedule.base_date_source if schedule else snapshot.payment_source,
        "due_date": schedule.due_date.isoformat() if schedule else None,
        "next_due_date": schedule.next_due_date.isoformat() if schedule else None,
        "scheduled_at": _scheduled_datetime(schedule.due_date).isoformat() if schedule else None,
        "estado_pago": snapshot.payment_status,
        "fuente_estado_pago": snapshot.payment_status_source,
        "should_send": should_send,
        "reason": reason,
        "test_phone_allowed": is_test_phone_allowed(snapshot.phone),
        "bridge_endpoint": "collections/account/payments",
        "bridge_found": snapshot.bridge_found,
        "fecha_venta": snapshot.sale_date.isoformat() if snapshot.sale_date else None,
        "payment_day_source": schedule.source if schedule else snapshot.payment_source,
        "fallback_used": bool(schedule.fallback_used) if schedule else False,
        "fallback_reason": schedule.fallback_reason if schedule else None,
        "classification": classification,
        "template_name": template_name,
        "reminder_type": reminder_type,
        "dry_run": dry_run,
        "would_send": should_send,
        "would_schedule_next": bool(schedule and classification not in {CLASS_SETTLED, CLASS_BRIDGE_ERROR, CLASS_INSUFFICIENT_BRIDGE_DATA}),
        "would_cancel_settled": classification == CLASS_SETTLED,
        "missing_fields": snapshot.missing_fields or [],
    }


async def dry_run_payment_reminder(
    db: Session,
    *,
    cuenta: str | None,
    folio: str | None = None,
    company_id: int | None = None,
    client: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    company_id = int(company_id or settings.PAYMENT_REMINDER_COMPANY_ID)
    today = today or mexico_now_naive().date()
    snapshot = await fetch_bridge_account_snapshot(
        cuenta=cuenta,
        folio=folio,
        company_id=company_id,
        client=client,
    )
    if snapshot.error_code:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_BRIDGE_ERROR,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            reason=snapshot.error_message_sanitized,
        )
    if snapshot.settled:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_SETTLED,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            reason="settled_confirmed_by_bridge",
        )
    if snapshot.missing_fields:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            reason="missing_bridge_fields",
        )

    try:
        schedule = calculate_snapshot_due_schedule(snapshot, today=today)
    except PaymentScheduleError as exc:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            reason=str(exc),
        )
    classification = classify_reminder_case(
        bridge_found=snapshot.bridge_found,
        missing_fields=snapshot.missing_fields,
        payment_status=snapshot.payment_status,
        due_date=schedule.due_date,
        today=today,
    )
    template_name, reminder_type = _template_for_classification(classification)
    return _build_process_result(
        snapshot=snapshot,
        schedule=schedule,
        classification=classification,
        template_name=template_name,
        reminder_type=reminder_type,
        dry_run=True,
        reason=None,
    )


async def process_due_payment_reminder(
    db: Session,
    reminder: PaymentReminder,
    *,
    company_id: int | None = None,
    client: Any | None = None,
    dry_run: bool | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    company_id = int(company_id or settings.PAYMENT_REMINDER_COMPANY_ID)
    dry_run = settings.PAYMENT_REMINDERS_DRY_RUN if dry_run is None else bool(dry_run)
    today = today or mexico_now_naive().date()

    snapshot = await fetch_bridge_account_snapshot(
        cuenta=reminder.cuenta,
        folio=reminder.folio,
        company_id=company_id,
        client=client,
    )

    if snapshot.error_code:
        if not dry_run:
            _mark_result(
                reminder,
                status=STATUS_FAILED,
                error_code="bridge_error",
                error_message=snapshot.error_message_sanitized,
            )
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_BRIDGE_ERROR,
            template_name=None,
            reminder_type=None,
            dry_run=dry_run,
            reason=snapshot.error_message_sanitized,
        )

    if snapshot.settled:
        result = _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_SETTLED,
            template_name=None,
            reminder_type=None,
            dry_run=dry_run,
            reason="settled_confirmed_by_bridge",
        )
        if not dry_run:
            reminder.bridge_found = snapshot.bridge_found
            reminder.bridge_snapshot_hash = snapshot.snapshot_hash
            reminder.saldo_snapshot = snapshot.balance
            reminder.monto_minimo_snapshot = snapshot.minimum_payment
            _mark_result(reminder, status=STATUS_CANCELLED_SETTLED)
            if snapshot.cuenta:
                _cancel_future_settled(db, cuenta=snapshot.cuenta, current_id=reminder.id)
        return result

    if snapshot.missing_fields:
        if not dry_run:
            _mark_result(
                reminder,
                status=STATUS_SKIPPED,
                error_code=CLASS_INSUFFICIENT_BRIDGE_DATA,
                error_message="missing_fields:" + ",".join(snapshot.missing_fields),
            )
            reminder.bridge_found = snapshot.bridge_found
            reminder.bridge_snapshot_hash = snapshot.snapshot_hash
        logger.warning(
            "payment_reminder_missing_bridge_fields",
            extra={
                "cuenta_masked": _mask(snapshot.cuenta),
                "folio_masked": _mask(snapshot.folio),
                "missing_fields": snapshot.missing_fields,
            },
        )
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
            template_name=None,
            reminder_type=None,
            dry_run=dry_run,
            reason="missing_bridge_fields",
        )

    try:
        schedule = calculate_snapshot_due_schedule(snapshot, today=today)
    except PaymentScheduleError as exc:
        if not dry_run:
            _mark_result(
                reminder,
                status=STATUS_SKIPPED,
                error_code=CLASS_INSUFFICIENT_BRIDGE_DATA,
                error_message=str(exc),
            )
            reminder.bridge_found = snapshot.bridge_found
            reminder.bridge_snapshot_hash = snapshot.snapshot_hash
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
            template_name=None,
            reminder_type=None,
            dry_run=dry_run,
            reason=str(exc),
        )
    classification = classify_reminder_case(
        bridge_found=snapshot.bridge_found,
        missing_fields=snapshot.missing_fields,
        payment_status=snapshot.payment_status,
        due_date=schedule.due_date,
        today=today,
    )
    template_name, reminder_type = _template_for_classification(classification)

    result = _build_process_result(
        snapshot=snapshot,
        schedule=schedule,
        classification=classification,
        template_name=template_name,
        reminder_type=reminder_type,
        dry_run=dry_run,
    )

    if dry_run:
        return result

    _update_reminder_from_snapshot(
        reminder,
        snapshot=snapshot,
        schedule=schedule,
        template_name=template_name,
    )
    reminder.dry_run = False

    if classification == CLASS_SETTLED:
        _mark_result(reminder, status=STATUS_CANCELLED_SETTLED)
        _cancel_future_settled(db, cuenta=snapshot.cuenta, current_id=reminder.id)
        result["reason"] = "settled_confirmed_by_bridge"
        return result

    if classification == CLASS_NOT_DUE:
        reminder.status = STATUS_SCHEDULED
        reminder.scheduled_for = _scheduled_datetime(schedule.due_date)
        result["reason"] = "not_due"
        return result

    if not template_name or not reminder_type:
        _mark_result(
            reminder,
            status=STATUS_FAILED,
            error_code="template_missing",
            error_message="meta_template_not_configured",
        )
        result["reason"] = "template_missing"
        return result

    already_sent = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.id != reminder.id)
        .filter(PaymentReminder.cuenta == snapshot.cuenta)
        .filter(PaymentReminder.due_date == schedule.due_date)
        .filter(PaymentReminder.reminder_type == reminder_type)
        .filter(PaymentReminder.status == STATUS_SENT)
        .first()
    )
    if already_sent:
        _mark_result(
            reminder,
            status=STATUS_SKIPPED,
            error_code=CLASS_ALREADY_SENT,
            error_message="same_account_due_date_template_already_sent",
        )
        result["classification"] = CLASS_ALREADY_SENT
        result["reason"] = CLASS_ALREADY_SENT
        return result

    if not is_test_phone_allowed(snapshot.phone):
        _mark_result(
            reminder,
            status=STATUS_SKIPPED,
            error_code=CLASS_SKIPPED_TEST_PHONE_ONLY,
            error_message="phone_not_allowed_by_TEST_PHONE_ONLY",
        )
        result["classification"] = CLASS_SKIPPED_TEST_PHONE_ONLY
        result["reason"] = CLASS_SKIPPED_TEST_PHONE_ONLY
        logger.info(
            "payment_reminder_skipped_test_phone_only",
            extra={
                "cuenta_masked": _mask(snapshot.cuenta),
                "phone_last4": _mask(snapshot.phone),
            },
        )
        return result

    parameters = build_template_parameters(
        reminder_type=reminder_type,
        snapshot=snapshot,
        schedule=schedule,
    )
    response = await send_template_message(
        snapshot.phone,
        template_name,
        parameters,
        language=settings.META_TEMPLATE_LANGUAGE,
    )
    status_code = getattr(response, "status_code", None)
    if response is None or (status_code is not None and status_code >= 400):
        _mark_result(
            reminder,
            status=STATUS_FAILED,
            error_code="meta_error",
            error_message=f"meta_status_{status_code or 'none'}",
        )
        result["reason"] = "meta_error"
        return result

    reminder.reminder_type = reminder_type
    reminder.meta_message_id = _response_meta_message_id(response)
    _mark_result(reminder, status=STATUS_SENT)

    next_template, next_type = _template_for_classification(CLASS_NOT_DUE)
    upsert_scheduled_reminder(
        db,
        snapshot=snapshot,
        schedule=PaymentSchedule(
            due_date=schedule.next_due_date,
            next_due_date=schedule.next_due_date + timedelta(days=7),
            weekday=schedule.weekday,
            source=schedule.source,
        ),
        reminder_type=next_type or REMINDER_PAYMENT_PENDING,
        template_name=next_template,
    )
    result["reason"] = "sent"
    result["meta_message_id"] = reminder.meta_message_id
    return result


async def run_due_payment_reminders(
    db: Session,
    *,
    company_id: int | None = None,
    limit: int = 100,
    dry_run: bool | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    now = mexico_now_naive()
    reminders = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.status.in_(list(ACTIVE_REMINDER_STATUSES)))
        .filter(PaymentReminder.scheduled_for <= now)
        .order_by(PaymentReminder.scheduled_for.asc(), PaymentReminder.id.asc())
        .limit(limit)
        .all()
    )
    results = []
    for reminder in reminders:
        try:
            result = await process_due_payment_reminder(
                db,
                reminder,
                company_id=company_id,
                client=client,
                dry_run=dry_run,
            )
            results.append(result)
            if not (settings.PAYMENT_REMINDERS_DRY_RUN if dry_run is None else dry_run):
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception(
                "payment_reminder_processing_exception",
                extra={
                    "reminder_id": reminder.id,
                    "cuenta_masked": _mask(reminder.cuenta),
                    "error_type": exc.__class__.__name__,
                },
            )
            raise
    return {"processed": len(results), "results": results}


async def sync_payment_reminder_candidates(
    db: Session,
    *,
    company_id: int | None = None,
    limit: int | None = None,
    dry_run: bool | None = None,
    client: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    company_id = int(company_id or settings.PAYMENT_REMINDER_COMPANY_ID)
    limit = int(limit or settings.PAYMENT_REMINDER_SYNC_LIMIT or 100)
    dry_run = settings.PAYMENT_REMINDERS_DRY_RUN if dry_run is None else bool(dry_run)
    today = today or mexico_now_naive().date()
    client = client or get_siga_bridge_client()

    try:
        payload = await client.get_collections(
            company_id,
            include_paid=False,
            active_only=True,
            limit=limit,
            bypass_cache=True,
        )
    except SigaBridgeError as exc:
        logger.warning(
            "payment_reminder_candidate_sync_bridge_error",
            extra={
                "company_id": company_id,
                "error_type": exc.__class__.__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
        return {"synced": 0, "error": "bridge_error", "results": []}

    results = []
    for record in _collection_records_from_payload(payload):
        normalized = normalize_collection_record(
            record,
            source="siga_bridge",
            bridge_status="ok",
            prefer_payment_total=False,
        )
        normalized = _preserve_payment_schedule_fields(normalized, record)
        snapshot = _snapshot_from_item(normalized, company_id=company_id)
        if snapshot.settled:
            if not dry_run and snapshot.cuenta:
                _cancel_future_settled(db, cuenta=snapshot.cuenta)
            results.append(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_SETTLED,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    reason="settled_confirmed_by_bridge",
                )
            )
            continue
        if snapshot.missing_fields:
            results.append(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    reason="missing_bridge_fields",
                )
            )
            continue

        try:
            schedule = calculate_snapshot_due_schedule(snapshot, today=today)
        except PaymentScheduleError as exc:
            results.append(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    reason=str(exc),
                )
            )
            continue

        classification = classify_reminder_case(
            bridge_found=snapshot.bridge_found,
            missing_fields=snapshot.missing_fields,
            payment_status=snapshot.payment_status,
            due_date=schedule.due_date,
            today=today,
        )
        template_name, reminder_type = _template_for_classification(classification)
        if not reminder_type:
            reminder_type = REMINDER_PAYMENT_PENDING
        _, status = upsert_scheduled_reminder(
            db,
            snapshot=snapshot,
            schedule=schedule,
            reminder_type=reminder_type,
            template_name=template_name,
            dry_run=dry_run,
        )
        result = _build_process_result(
            snapshot=snapshot,
            schedule=schedule,
            classification=status if status in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT} else classification,
            template_name=template_name,
            reminder_type=reminder_type,
            dry_run=dry_run,
            reason=status,
        )
        results.append(result)

    if not dry_run:
        db.commit()
    return {"synced": len(results), "results": results}
