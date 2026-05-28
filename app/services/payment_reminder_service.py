from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.whatsapp_client import send_template_message
from app.config.settings import settings
from app.db.models import ChatSessions, Message, PaymentReminder
from app.services.message_service import save_message
from app.services.collections_panel_service import (
    normalize_collection_record,
    normalize_payments,
    resolve_collection_payment_state,
)
from app.services.siga_bridge import SigaBridgeError, get_siga_bridge_client
from app.services.ws_events import build_new_message_event
from app.utils.account_reference import format_account_reference, resolve_payment_account_reference
from app.utils.timezone import mexico_now_naive
from app.websockets.manager import manager


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
CLASS_MISSING_CHAT_SESSION = "missing_chat_session"
CLASS_AMBIGUOUS_CHAT_SESSION = "ambiguous_chat_session"
CLASS_CHAT_SESSION_ACCOUNT_MISMATCH = "chat_session_account_mismatch"

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
class ChatSessionResolution:
    session: ChatSessions | None
    found: bool
    reason: str
    matched_by: str | None = None
    candidates_count: int = 0

    @property
    def session_id(self) -> int | None:
        return getattr(self.session, "id", None) if self.session else None


@dataclass(slots=True)
class ReminderStats:
    sent_count: int = 0
    last_sent_at: datetime | None = None
    next_scheduled_at: datetime | None = None


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


def _conversation_phone_key(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("52") and len(digits) > 10:
        digits = digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def _phone_lookup_values(value: Any) -> list[str]:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    normalized = normalize_phone_for_whatsapp(value)
    local10 = _conversation_phone_key(value)
    candidates = [
        normalized,
        digits or None,
        local10,
        f"52{local10}" if local10 and len(local10) == 10 else None,
        f"521{local10}" if local10 and len(local10) == 10 else None,
    ]
    seen: set[str] = set()
    values: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            values.append(candidate)
            seen.add(candidate)
    return values


def _clean_match_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalized_folio(value: Any) -> str | None:
    text = _clean_match_text(value)
    return text.upper() if text else None


def _normalized_account(value: Any) -> str | None:
    text = _clean_match_text(value)
    return text.upper() if text else None


def _account_values_match(candidate: Any, expected: Any) -> bool:
    candidate_text = _normalized_account(candidate)
    expected_text = _normalized_account(expected)
    if not candidate_text or not expected_text:
        return False
    if candidate_text == expected_text:
        return True
    candidate_prefixed = candidate_text[:1] in {"A", "B"}
    expected_prefixed = expected_text[:1] in {"A", "B"}
    if candidate_prefixed and not expected_prefixed:
        return candidate_text[1:] == expected_text
    if expected_prefixed and candidate_prefixed:
        return candidate_text == expected_text
    return False


def _collect_values_by_keys(data: Any, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            key_text = str(key).lower()
            if key_text in keys and value not in (None, "", [], {}):
                if isinstance(value, Mapping):
                    nested = value.get("value") or value.get("id") or value.get("cuenta")
                    if nested not in (None, "", [], {}):
                        values.append(str(nested).strip())
                elif not isinstance(value, list):
                    values.append(str(value).strip())
            if isinstance(value, (Mapping, list)):
                values.extend(_collect_values_by_keys(value, keys))
    elif isinstance(data, list):
        for item in data:
            values.extend(_collect_values_by_keys(item, keys))
    return [value for value in values if value]


def _session_folio_match(session: ChatSessions, folio: str | None) -> bool | None:
    expected = _normalized_folio(folio)
    if not expected:
        return None
    values = []
    direct = _normalized_folio(getattr(session, "folio", None))
    if direct:
        values.append(direct)
    values.extend(
        _normalized_folio(value)
        for value in _collect_values_by_keys(getattr(session, "extra_json", None), {"folio"})
    )
    clean_values = [value for value in values if value]
    if not clean_values:
        return None
    return expected in clean_values


def _session_account_match(session: ChatSessions, cuenta: str | None) -> bool | None:
    expected = _normalized_account(cuenta)
    if not expected:
        return None
    values = _collect_values_by_keys(
        getattr(session, "extra_json", None),
        {
            "no_cuenta",
            "cuenta",
            "numero_cuenta",
            "account",
            "account_number",
            "account_reference",
            "cuenta_formateada",
            "numero_cuenta_referencia",
        },
    )
    if not values:
        return None
    return any(_account_values_match(value, expected) for value in values)


def resolve_chat_session_for_reminder(
    db: Session,
    *,
    snapshot: BridgeAccountSnapshot | None = None,
    phone: str | None = None,
    folio: str | None = None,
    cuenta: str | None = None,
    session_id: int | None = None,
) -> ChatSessionResolution:
    expected_phone = normalize_phone_for_whatsapp(phone or (snapshot.phone if snapshot else None))
    expected_folio = folio or (snapshot.folio if snapshot else None)
    expected_account = (
        cuenta
        or (snapshot.account_reference_formatted if snapshot else None)
        or (snapshot.cuenta if snapshot else None)
    )

    if session_id:
        session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()
        if not session:
            return ChatSessionResolution(None, False, CLASS_MISSING_CHAT_SESSION)
        phone_key = _conversation_phone_key(expected_phone)
        session_phone_key = _conversation_phone_key(session.phone)
        if phone_key and session_phone_key and phone_key != session_phone_key:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=1)
        folio_match = _session_folio_match(session, expected_folio)
        if folio_match is False:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=1)
        account_match = _session_account_match(session, expected_account)
        if account_match is False:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=1)
        return ChatSessionResolution(session, True, "existing_session_id", "session_id", 1)

    lookup_values = _phone_lookup_values(expected_phone)
    if not lookup_values:
        return ChatSessionResolution(None, False, CLASS_MISSING_CHAT_SESSION)

    local10 = _conversation_phone_key(expected_phone)
    phone_filter = ChatSessions.phone.in_(lookup_values)
    if local10 and len(local10) == 10:
        phone_filter = or_(phone_filter, ChatSessions.phone.like(f"%{local10}"))
    sessions = (
        db.query(ChatSessions)
        .filter(phone_filter)
        .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
        .all()
    )

    phone_key = _conversation_phone_key(expected_phone)
    sessions = [
        session
        for session in sessions
        if not phone_key or _conversation_phone_key(session.phone) == phone_key
    ]
    if not sessions:
        return ChatSessionResolution(None, False, CLASS_MISSING_CHAT_SESSION)

    folio_matches = [session for session in sessions if _session_folio_match(session, expected_folio) is True]
    if len(folio_matches) == 1:
        account_match = _session_account_match(folio_matches[0], expected_account)
        if account_match is False:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=len(sessions))
        return ChatSessionResolution(folio_matches[0], True, "folio_match", "folio", len(sessions))
    if len(folio_matches) > 1:
        account_matches = [
            session for session in folio_matches if _session_account_match(session, expected_account) is True
        ]
        if len(account_matches) == 1:
            return ChatSessionResolution(account_matches[0], True, "folio_account_match", "folio_account", len(sessions))
        return ChatSessionResolution(None, False, CLASS_AMBIGUOUS_CHAT_SESSION, candidates_count=len(sessions))

    account_matches = [session for session in sessions if _session_account_match(session, expected_account) is True]
    if len(account_matches) == 1:
        return ChatSessionResolution(account_matches[0], True, "account_match", "account", len(sessions))
    if len(account_matches) > 1:
        return ChatSessionResolution(None, False, CLASS_AMBIGUOUS_CHAT_SESSION, candidates_count=len(sessions))

    if len(sessions) == 1:
        session = sessions[0]
        folio_match = _session_folio_match(session, expected_folio)
        if folio_match is False:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=1)
        account_match = _session_account_match(session, expected_account)
        if account_match is False:
            return ChatSessionResolution(None, False, CLASS_CHAT_SESSION_ACCOUNT_MISMATCH, candidates_count=1)
        return ChatSessionResolution(session, True, "single_phone_match", "phone", 1)

    return ChatSessionResolution(None, False, CLASS_AMBIGUOUS_CHAT_SESSION, candidates_count=len(sessions))


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


async def _record_sent_conversation_message(
    db: Session,
    *,
    session: ChatSessions,
    reminder: PaymentReminder,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule,
    reminder_type: str,
    meta_message_id: str | None,
) -> Message | None:
    if meta_message_id:
        existing = db.query(Message).filter(Message.message_id == meta_message_id).first()
        if existing:
            return existing

    now = mexico_now_naive()
    content = _build_conversation_message_preview(snapshot=snapshot, schedule=schedule)
    message = save_message(
        db=db,
        session_id=session.id,
        phone=session.phone or snapshot.phone or reminder.phone,
        direction="out",
        content=content,
        message_id=meta_message_id,
        type="payment_reminder",
        created_at=now,
        extra_json={
            "source": "payment_reminder",
            "reminder_id": reminder.id,
            "cuenta": snapshot.account_reference_formatted or snapshot.cuenta,
            "folio": snapshot.folio,
            "due_date": schedule.due_date.isoformat(),
            "next_due_date": schedule.next_due_date.isoformat(),
            "reminder_type": reminder_type,
            "template_name": reminder.template_name,
            "meta_message_id": meta_message_id,
        },
    )
    session.last_message = content
    session.last_message_at = now
    if meta_message_id:
        session.last_message_id = meta_message_id
    session.unread_count = 0
    db.flush()
    await manager.send_to_all(build_new_message_event(session, message))
    await manager.send_to_all(
        {
            "type": "dashboard_update",
            "payload": {
                "messages_in_delta": 0,
                "messages_out_delta": 1,
                "session_id": session.id,
            },
        }
    )
    return message


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
    session_id: int | None = None,
) -> None:
    if session_id is not None:
        reminder.session_id = session_id
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
    session_id: int | None = None,
    dry_run: bool = False,
) -> tuple[PaymentReminder | None, str]:
    if not snapshot.cuenta or not snapshot.phone:
        return None, CLASS_INSUFFICIENT_BRIDGE_DATA
    if session_id is None and not dry_run:
        return None, CLASS_MISSING_CHAT_SESSION
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
                session_id=session_id,
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
            session_id=session_id,
        )
        existing.status = STATUS_SCHEDULED
        existing.error_code = None
        existing.error_message_sanitized = None
        return existing, STATUS_SCHEDULED

    reminder = PaymentReminder(
        session_id=session_id,
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


def _reminder_stats(
    db: Session,
    *,
    cuenta: str | None = None,
    session_id: int | None = None,
) -> ReminderStats:
    try:
        query = db.query(PaymentReminder)
        if cuenta:
            query = query.filter(PaymentReminder.cuenta == cuenta)
        elif session_id:
            query = query.filter(PaymentReminder.session_id == session_id)
        else:
            return ReminderStats()

        sent_rows = query.filter(PaymentReminder.status == STATUS_SENT).all()
        scheduled_rows = query.filter(PaymentReminder.status == STATUS_SCHEDULED).all()
        return ReminderStats(
            sent_count=len(sent_rows),
            last_sent_at=max(
                (row.sent_at for row in sent_rows if row.sent_at),
                default=None,
            ),
            next_scheduled_at=min(
                (row.scheduled_for for row in scheduled_rows if row.scheduled_for),
                default=None,
            ),
        )
    except Exception:
        logger.warning(
            "payment_reminder_stats_failed",
            extra={"cuenta_masked": _mask(cuenta), "session_id": session_id},
            exc_info=True,
        )
        return ReminderStats()


def _build_conversation_message_preview(
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule | None,
) -> str:
    cuenta = snapshot.account_reference_formatted or format_account_reference(snapshot.cuenta) or snapshot.cuenta or "N/D"
    minimum = _money_text(snapshot.minimum_payment)
    due = _date_text(schedule.due_date if schedule else None)
    return f"Recordatorio de pago enviado: cuenta {cuenta}, pago minimo {minimum}, vencimiento {due}."


def _build_process_result(
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule | None,
    classification: str,
    template_name: str | None,
    reminder_type: str | None,
    dry_run: bool,
    session_resolution: ChatSessionResolution | None = None,
    reminder_stats: ReminderStats | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    cuenta_formateada = snapshot.account_reference_formatted or format_account_reference(snapshot.cuenta)
    cuenta_formateada_valida = bool(
        (snapshot.account_reference_valid and snapshot.account_reference_formatted)
        or (cuenta_formateada and not snapshot.account_reference_reason)
    )
    test_phone_allowed = is_test_phone_allowed(snapshot.phone)
    send_candidate = bool(
        template_name
        and snapshot.payment_status == PAYMENT_STATUS_UNPAID
        and cuenta_formateada_valida
        and classification not in {CLASS_NOT_DUE, CLASS_SETTLED, CLASS_BRIDGE_ERROR, CLASS_INSUFFICIENT_BRIDGE_DATA}
        and (session_resolution is None or session_resolution.found)
    )
    should_send = bool(send_candidate and test_phone_allowed)
    resolved_reason = reason
    if resolved_reason is None and send_candidate and not test_phone_allowed:
        resolved_reason = CLASS_SKIPPED_TEST_PHONE_ONLY
    preview = _build_conversation_message_preview(snapshot=snapshot, schedule=schedule) if schedule else None
    session_found = bool(session_resolution.found) if session_resolution else None
    session_id = session_resolution.session_id if session_resolution else None
    stats = reminder_stats or ReminderStats()
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
        "reason": resolved_reason,
        "test_phone_allowed": test_phone_allowed,
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
        "session_id": session_id,
        "chat_session_found": session_found,
        "chat_session_match_reason": session_resolution.reason if session_resolution else None,
        "chat_session_candidates_count": session_resolution.candidates_count if session_resolution else None,
        "would_create_conversation_message": bool(should_send and session_found),
        "conversation_message_preview": preview if should_send else None,
        "next_payment_reminder_at": stats.next_scheduled_at.isoformat() if stats.next_scheduled_at else None,
        "sent_count_prev": stats.sent_count,
        "last_payment_reminder_at": stats.last_sent_at.isoformat() if stats.last_sent_at else None,
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
    session_resolution = resolve_chat_session_for_reminder(
        db,
        snapshot=snapshot,
        phone=snapshot.phone,
        folio=snapshot.folio or folio,
        cuenta=snapshot.account_reference_formatted or snapshot.cuenta or cuenta,
    )
    stats = _reminder_stats(
        db,
        cuenta=snapshot.cuenta or cuenta,
        session_id=session_resolution.session_id,
    )
    if snapshot.error_code:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=CLASS_BRIDGE_ERROR,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            session_resolution=session_resolution,
            reminder_stats=stats,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason="missing_bridge_fields",
        )
    if not session_resolution.found:
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=session_resolution.reason,
            template_name=None,
            reminder_type=None,
            dry_run=True,
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason=session_resolution.reason,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
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
        session_resolution=session_resolution,
        reminder_stats=stats,
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
    session_resolution = resolve_chat_session_for_reminder(
        db,
        snapshot=snapshot,
        phone=snapshot.phone or reminder.phone,
        folio=snapshot.folio or reminder.folio,
        cuenta=snapshot.account_reference_formatted or snapshot.cuenta or reminder.cuenta,
        session_id=getattr(reminder, "session_id", None),
    )
    stats = _reminder_stats(
        db,
        cuenta=snapshot.cuenta or reminder.cuenta,
        session_id=session_resolution.session_id,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason="missing_bridge_fields",
        )

    if not session_resolution.found:
        if not dry_run:
            _mark_result(
                reminder,
                status=STATUS_SKIPPED,
                error_code=session_resolution.reason,
                error_message=session_resolution.reason,
            )
        logger.info(
            "payment_reminder_skipped_chat_session",
            extra={
                "cuenta_masked": _mask(snapshot.cuenta or reminder.cuenta),
                "folio_masked": _mask(snapshot.folio or reminder.folio),
                "phone_last4": _mask(snapshot.phone or reminder.phone),
                "reason": session_resolution.reason,
                "candidates_count": session_resolution.candidates_count,
            },
        )
        return _build_process_result(
            snapshot=snapshot,
            schedule=None,
            classification=session_resolution.reason,
            template_name=None,
            reminder_type=None,
            dry_run=dry_run,
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason=session_resolution.reason,
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
            session_resolution=session_resolution,
            reminder_stats=stats,
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
        session_resolution=session_resolution,
        reminder_stats=stats,
    )

    if dry_run:
        return result

    _update_reminder_from_snapshot(
        reminder,
        snapshot=snapshot,
        schedule=schedule,
        template_name=template_name,
        session_id=session_resolution.session_id,
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
    result["conversation_message_created"] = False
    try:
        message = await _record_sent_conversation_message(
            db,
            session=session_resolution.session,
            reminder=reminder,
            snapshot=snapshot,
            schedule=schedule,
            reminder_type=reminder_type,
            meta_message_id=reminder.meta_message_id,
        )
        result["conversation_message_created"] = bool(message)
    except Exception:
        logger.exception(
            "payment_reminder_conversation_message_failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "session_id": session_resolution.session_id,
                "cuenta_masked": _mask(snapshot.cuenta),
            },
        )

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
        session_id=session_resolution.session_id,
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
        session_resolution = resolve_chat_session_for_reminder(
            db,
            snapshot=snapshot,
            phone=snapshot.phone,
            folio=snapshot.folio,
            cuenta=snapshot.account_reference_formatted or snapshot.cuenta,
        )
        stats = _reminder_stats(
            db,
            cuenta=snapshot.cuenta,
            session_id=session_resolution.session_id,
        )
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
                    session_resolution=session_resolution,
                    reminder_stats=stats,
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
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason="missing_bridge_fields",
                )
            )
            continue

        if not session_resolution.found:
            results.append(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=session_resolution.reason,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=session_resolution.reason,
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
                    session_resolution=session_resolution,
                    reminder_stats=stats,
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
            session_id=session_resolution.session_id,
            dry_run=dry_run,
        )
        result = _build_process_result(
            snapshot=snapshot,
            schedule=schedule,
            classification=status if status in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT} else classification,
            template_name=template_name,
            reminder_type=reminder_type,
            dry_run=dry_run,
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason=status,
        )
        results.append(result)

    if not dry_run:
        db.commit()
    return {"synced": len(results), "results": results}
