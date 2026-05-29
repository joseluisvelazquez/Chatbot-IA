from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import func, or_
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
STATUS_PROCESSING = "processing"
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
CLASS_ALREADY_TERMINAL = "already_terminal"
CLASS_MISSING_CHAT_SESSION = "missing_chat_session"
CLASS_AMBIGUOUS_CHAT_SESSION = "ambiguous_chat_session"
CLASS_CHAT_SESSION_ACCOUNT_MISMATCH = "chat_session_account_mismatch"

REASON_MISSING_BRIDGE_FIELDS = "missing_bridge_fields"
REASON_PAID_OR_SETTLED = "paid_or_settled"
REASON_TEMPLATE_MISSING = "template_missing"
REASON_META_ERROR = "meta_error"
REASON_AUDIT_FIELDS_MISSING = "audit_fields_missing"
REASON_TEST_PHONE_NOT_ALLOWED = "test_phone_not_allowed"
REASON_WEEKLY_FREQUENCY_BLOCKED = "weekly_frequency_blocked"
REASON_MESSAGE_INSERT_FAILED = "message_insert_failed"

OMISSION_REASONS = {
    CLASS_MISSING_CHAT_SESSION,
    CLASS_AMBIGUOUS_CHAT_SESSION,
    CLASS_CHAT_SESSION_ACCOUNT_MISMATCH,
    REASON_MISSING_BRIDGE_FIELDS,
    CLASS_BRIDGE_ERROR,
    CLASS_NOT_DUE,
    REASON_PAID_OR_SETTLED,
    CLASS_ALREADY_SENT,
    CLASS_ALREADY_TERMINAL,
    REASON_TEMPLATE_MISSING,
    REASON_META_ERROR,
    REASON_TEST_PHONE_NOT_ALLOWED,
    REASON_WEEKLY_FREQUENCY_BLOCKED,
    REASON_MESSAGE_INSERT_FAILED,
}

REMINDER_PAYMENT_PENDING = "payment_pending"
REMINDER_PAYMENT_OVERDUE = "payment_overdue"
REMINDER_NEXT_PAYMENT = "next_payment"
REMINDER_AUDIT = "payment_audit"

ACTIVE_REMINDER_STATUSES = {
    STATUS_SCHEDULED,
}

PROTECTED_REMINDER_STATUSES = {
    STATUS_SCHEDULED,
    STATUS_PROCESSING,
    STATUS_SENT,
}

PAYMENT_REMINDER_MIN_INTERVAL_DAYS = 7

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
    last_sent_reminder_id: int | None = None
    next_scheduled_at: datetime | None = None
    existing_scheduled_id: int | None = None


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
        if self.payment_status == PAYMENT_STATUS_PAID:
            return True
        if self.balance is not None and self.balance <= Decimal("0"):
            return True
        status_text = _strip_accents(f"{self.account_status or ''} {self.process or ''}".lower())
        return any(token in status_text for token in ("pagad", "liquidad", "saldad"))


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


def payment_reminders_test_mode_enabled() -> bool:
    return bool(getattr(settings, "PAYMENT_REMINDERS_TEST_MODE", False))


def _configured_test_phones() -> set[str]:
    raw = getattr(settings, "TEST_PHONE_ONLY", "") or ""
    values: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            values = []
        else:
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                values = parsed
            else:
                values = [part.strip() for part in text.split(",")]
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    return {
        normalized
        for normalized in (normalize_phone_for_whatsapp(value) for value in values)
        if normalized
    }


def payment_reminder_test_phone_allowed(phone: Any) -> bool:
    if not payment_reminders_test_mode_enabled():
        return True
    normalized = normalize_phone_for_whatsapp(phone)
    return bool(normalized and normalized in _configured_test_phones())


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
    if expected_prefixed and not candidate_prefixed:
        return expected_text[1:] == candidate_text
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


def _session_account_candidate(session: ChatSessions) -> str | None:
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
    return values[0] if values else None


def _session_folio_candidate(session: ChatSessions) -> str | None:
    direct = _clean_text(getattr(session, "folio", None))
    if direct:
        return direct
    values = _collect_values_by_keys(getattr(session, "extra_json", None), {"folio"})
    return values[0] if values else None


def _json_path_has_value(path: str):
    value = func.JSON_UNQUOTE(func.JSON_EXTRACT(ChatSessions.extra_json, path))
    value = func.NULLIF(func.NULLIF(value, ""), "null")
    return value.isnot(None)


def _chat_session_payment_candidates(db: Session, *, limit: int) -> list[ChatSessions]:
    has_folio = ChatSessions.folio.isnot(None) & (ChatSessions.folio != "")
    has_account_in_extra = or_(
        _json_path_has_value("$.no_cuenta"),
        _json_path_has_value("$.cuenta"),
        _json_path_has_value("$.numero_cuenta"),
        _json_path_has_value("$.account"),
        _json_path_has_value("$.account_reference"),
        _json_path_has_value("$.cuenta_formateada"),
        _json_path_has_value("$.siga_bridge.lookup.no_cuenta"),
        _json_path_has_value("$.siga_bridge.lookup.cuenta"),
        _json_path_has_value("$.siga_bridge.lookup.account"),
        _json_path_has_value("$.siga_bridge.lookup.account_reference"),
        _json_path_has_value("$.siga_bridge.snapshot.no_cuenta"),
        _json_path_has_value("$.siga_bridge.snapshot.cuenta"),
        _json_path_has_value("$.siga_bridge.snapshot.account"),
        _json_path_has_value("$.siga_bridge.snapshot.account_reference"),
        _json_path_has_value("$.siga_bridge.account.no_cuenta"),
        _json_path_has_value("$.siga_bridge.account.cuenta"),
        _json_path_has_value("$.siga_bridge.account.account"),
        _json_path_has_value("$.siga_bridge.account.account_reference"),
        _json_path_has_value("$.siga_bridge.verification_cache.snapshot.no_cuenta"),
        _json_path_has_value("$.siga_bridge.verification_cache.snapshot.cuenta"),
        _json_path_has_value("$.siga_bridge.verification_cache.snapshot.account"),
        _json_path_has_value("$.siga_bridge.verification_cache.snapshot.account_reference"),
        _json_path_has_value("$.siga_bridge.verification_cache.snapshot.cuenta_formateada"),
        _json_path_has_value("$.siga_bridge.verification_cache.lookup.no_cuenta"),
        _json_path_has_value("$.siga_bridge.verification_cache.lookup.cuenta"),
        _json_path_has_value("$.siga_bridge.verification_cache.lookup.account"),
        _json_path_has_value("$.siga_bridge.verification_cache.lookup.account_reference"),
    )
    return (
        db.query(ChatSessions)
        .filter(ChatSessions.phone.isnot(None))
        .filter(or_(has_folio, has_account_in_extra))
        .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
        .limit(limit)
        .all()
    )


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
    payload = _unwrap_bridge_payload(payload)
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = payload.get("items") or payload.get("accounts") or payload.get("data") or []
        if isinstance(raw_items, Mapping):
            raw_items = raw_items.get("items") or raw_items.get("accounts") or [raw_items]
    else:
        raw_items = []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _unwrap_bridge_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping) and {"ok", "data"}.issubset(payload.keys()):
        return payload.get("data") if payload.get("ok") is not False else None
    return payload


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
    account_payload = _unwrap_bridge_payload(account_payload)
    payments_payload = _unwrap_bridge_payload(payments_payload)
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
    if (
        not snapshot.next_payment_date
        and not snapshot.payment_base_date
        and not snapshot.sale_date
        and not settings.PAYMENT_REMINDER_DEFAULT_WEEKDAY
    ):
        missing.append("fecha_base_o_fecha_venta")
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
        logger.info(
            "payment_reminder.create.start",
            extra={
                "account": _mask(cuenta),
                "folio_masked": _mask(folio),
                "company_id": company_id,
                "source": "siga_bridge",
            },
        )
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

        account_data = _unwrap_bridge_payload(account_payload)
        customer_data = account_data.get("customer") if isinstance(account_data, Mapping) else None
        account_node = account_data.get("account") if isinstance(account_data, Mapping) else None
        phones = customer_data.get("phones") if isinstance(customer_data, Mapping) else None
        logger.info(
            "payment_reminder.bridge.loaded",
            extra={
                "account": _mask(resolved_cuenta or cuenta),
                "company_id": company_id,
                "has_collection": bool(collection_record),
                "has_account": bool(account_node or account_data),
                "has_customer": isinstance(customer_data, Mapping),
                "phones_count": len(phones) if isinstance(phones, list) else 0,
            },
        )
        merged = _merge_record(collection_record, account_payload, payments_payload)
        if resolved_cuenta and merged.get("no_cuenta") in (None, ""):
            merged["no_cuenta"] = resolved_cuenta
        normalized = normalize_collection_record(
            merged,
            payments=normalize_payments(_unwrap_bridge_payload(payments_payload)),
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
            "payment_reminder.normalized",
            extra={
                "company_id": company_id,
                "account": _mask(snapshot.cuenta),
                "phone_masked": _mask(snapshot.phone),
                "minimum_payment": str(snapshot.minimum_payment) if snapshot.minimum_payment is not None else None,
                "balance": str(snapshot.balance) if snapshot.balance is not None else None,
                "status": snapshot.account_status,
                "account_process": snapshot.process,
                "payment_status": snapshot.payment_status,
                "sale_date": snapshot.sale_date.isoformat() if snapshot.sale_date else None,
            },
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
        logger.info(
            "payment_reminder.validation.ok" if not snapshot.missing_fields else "payment_reminder.validation.failed",
            extra={
                "account": _mask(snapshot.cuenta),
                "company_id": company_id,
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
    except Exception as exc:
        logger.exception(
            "payment_reminder_bridge_error",
            extra={
                "company_id": company_id,
                "cuenta_masked": _mask(cuenta),
                "folio_masked": _mask(folio),
                "error_type": exc.__class__.__name__,
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
    except Exception as exc:
        logger.warning(
            "payment_reminder_meta_response_parse_failed",
            extra={"error_type": exc.__class__.__name__},
        )
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
    content = _build_conversation_message_preview(
        snapshot=snapshot,
        schedule=schedule,
        template_name=reminder.template_name,
        sent_at=now,
    )
    logger.info(
        "payment_reminder.message.insert.start",
        extra={
            "reminder_id": getattr(reminder, "id", None),
            "session_id": getattr(session, "id", None),
            "account": _mask(snapshot.cuenta),
            "meta_message_id": meta_message_id,
        },
    )
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
    logger.info(
        "payment_reminder.message.inserted",
        extra={
            "reminder_id": getattr(reminder, "id", None),
            "message_db_id": getattr(message, "id", None),
            "session_id": getattr(session, "id", None),
            "meta_message_id": meta_message_id,
        },
    )
    try:
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
    except Exception as exc:
        logger.warning(
            "payment_reminder.message.websocket_failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "message_db_id": getattr(message, "id", None),
                "session_id": getattr(session, "id", None),
                "error_type": exc.__class__.__name__,
            },
            exc_info=True,
        )
    return message


def _existing_reminder(
    db: Session,
    *,
    cuenta: str,
    due_date: date,
    reminder_type: str,
    session_id: int | None = None,
) -> PaymentReminder | None:
    query = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.cuenta == cuenta)
        .filter(PaymentReminder.due_date == due_date)
        .filter(PaymentReminder.reminder_type == reminder_type)
    )
    if session_id is not None:
        session_match = query.filter(PaymentReminder.session_id == session_id).first()
        if session_match:
            return session_match
    return query.first()


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
        session_id=session_id,
    )
    if existing and existing.status == STATUS_SENT:
        logger.info(
            "payment_reminder.duplicate.prevented",
            extra={
                "payment_reminder_id": getattr(existing, "id", None),
                "account": _mask(snapshot.cuenta),
                "session_id": session_id,
                "due_date": schedule.due_date.isoformat(),
                "reminder_type": reminder_type,
                "existing_status": existing.status,
            },
        )
        return existing, CLASS_ALREADY_SENT
    if existing and existing.status in {STATUS_FAILED, STATUS_SKIPPED, STATUS_CANCELLED, STATUS_CANCELLED_SETTLED}:
        logger.info(
            "payment_reminder.duplicate.prevented",
            extra={
                "payment_reminder_id": getattr(existing, "id", None),
                "account": _mask(snapshot.cuenta),
                "session_id": session_id,
                "due_date": schedule.due_date.isoformat(),
                "reminder_type": reminder_type,
                "existing_status": existing.status,
                "reason": CLASS_ALREADY_TERMINAL,
            },
        )
        return existing, CLASS_ALREADY_TERMINAL
    if existing and existing.status in {STATUS_SCHEDULED, STATUS_PROCESSING}:
        logger.info(
            "payment_reminder.duplicate.prevented",
            extra={
                "payment_reminder_id": getattr(existing, "id", None),
                "account": _mask(snapshot.cuenta),
                "session_id": session_id,
                "due_date": schedule.due_date.isoformat(),
                "reminder_type": reminder_type,
                "existing_status": existing.status,
            },
        )
        if not dry_run:
            if existing.status == STATUS_SCHEDULED:
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
    db.flush()
    logger.info(
        "payment_reminder.create.inserted",
        extra={
            "payment_reminder_id": getattr(reminder, "id", None),
            "account": _mask(snapshot.cuenta),
            "session_id": session_id,
            "status": reminder.status,
            "scheduled_for": reminder.scheduled_for.isoformat() if reminder.scheduled_for else None,
            "reminder_type": reminder_type,
        },
    )
    return reminder, STATUS_SCHEDULED


def _audit_status_for_reason(classification: str | None, reason: str | None) -> str:
    canonical = _canonical_omission_reason(classification, reason)
    if canonical in {CLASS_BRIDGE_ERROR, REASON_META_ERROR, REASON_TEMPLATE_MISSING}:
        return STATUS_FAILED
    if canonical == REASON_PAID_OR_SETTLED or classification == CLASS_SETTLED:
        return STATUS_CANCELLED_SETTLED
    return STATUS_SKIPPED


def _audit_reminder_type(reminder_type: str | None) -> str:
    return reminder_type or REMINDER_AUDIT


def _audit_error_message(
    *,
    classification: str | None,
    reason: str | None,
    missing_fields: list[str] | None,
    error_message: str | None = None,
) -> str | None:
    parts = []
    canonical = _canonical_omission_reason(classification, reason)
    if canonical:
        parts.append(canonical)
    elif reason:
        parts.append(str(reason))
    elif classification:
        parts.append(str(classification))
    if missing_fields:
        parts.append("missing_fields:" + ",".join(missing_fields))
    if error_message:
        parts.append(str(error_message))
    message = " | ".join(part for part in parts if part)
    return message[:255] if message else None


def record_payment_reminder_audit(
    db: Session,
    *,
    snapshot: BridgeAccountSnapshot,
    schedule: PaymentSchedule | None,
    classification: str | None,
    reason: str | None,
    reminder_type: str | None = None,
    template_name: str | None = None,
    session_id: int | None = None,
    dry_run: bool = False,
) -> PaymentReminder | None:
    if dry_run:
        return None

    now = mexico_now_naive()
    due_date = schedule.due_date if schedule else now.date()
    scheduled_for = _scheduled_datetime(due_date) if schedule else now
    cuenta = (
        snapshot.cuenta
        or snapshot.account_reference_formatted
        or snapshot.account_reference_raw
    )
    if not cuenta:
        logger.warning(
            "payment_reminder.audit.skipped",
            extra={
                "reason": REASON_AUDIT_FIELDS_MISSING,
                "classification": classification,
                "folio_masked": _mask(snapshot.folio),
                "phone_masked": _mask(snapshot.phone),
            },
        )
        return None

    audit_type = _audit_reminder_type(reminder_type)
    canonical_reason = _canonical_omission_reason(classification, reason) or reason or classification
    status = _audit_status_for_reason(classification, reason)
    logger.info(
        "payment_reminder.create.insert.start",
        extra={
            "account": _mask(cuenta),
            "session_id": session_id,
            "status": status,
            "scheduled_for": scheduled_for.isoformat(),
            "reminder_type": audit_type,
            "skip_reason": canonical_reason,
        },
    )

    existing = _existing_reminder(
        db,
        cuenta=cuenta,
        due_date=due_date,
        reminder_type=audit_type,
        session_id=session_id,
    )
    error_message = _audit_error_message(
        classification=classification,
        reason=reason,
        missing_fields=snapshot.missing_fields or [],
        error_message=snapshot.error_message_sanitized,
    )
    if existing:
        if existing.status in PROTECTED_REMINDER_STATUSES:
            logger.info(
                "payment_reminder.duplicate.prevented",
                extra={
                    "payment_reminder_id": getattr(existing, "id", None),
                    "account": _mask(cuenta),
                    "session_id": session_id,
                    "due_date": due_date.isoformat(),
                    "reminder_type": audit_type,
                    "existing_status": existing.status,
                    "audit_reason": canonical_reason,
                },
            )
            return existing
        reminder = existing
        reminder.session_id = session_id if session_id is not None else reminder.session_id
        reminder.phone = snapshot.phone or reminder.phone or "unknown"
        reminder.folio = snapshot.folio or reminder.folio
        reminder.next_due_date = schedule.next_due_date if schedule else reminder.next_due_date
        reminder.scheduled_for = scheduled_for
        reminder.template_name = template_name
        reminder.status = status
        reminder.updated_at = now
    else:
        reminder = PaymentReminder(
            session_id=session_id,
            phone=snapshot.phone or "unknown",
            folio=snapshot.folio,
            cuenta=cuenta,
            due_date=due_date,
            next_due_date=schedule.next_due_date if schedule else None,
            scheduled_for=scheduled_for,
            reminder_type=audit_type,
            template_name=template_name,
            status=status,
            dry_run=False,
        )
        db.add(reminder)

    reminder.saldo_snapshot = snapshot.balance
    reminder.monto_minimo_snapshot = snapshot.minimum_payment
    reminder.bridge_found = snapshot.bridge_found
    reminder.bridge_snapshot_hash = snapshot.snapshot_hash
    reminder.error_code = str(canonical_reason or classification or reason or STATUS_SKIPPED)[:80]
    reminder.error_message_sanitized = error_message
    if status == STATUS_CANCELLED_SETTLED:
        reminder.cancelled_at = now
    db.flush()
    logger.info(
        "payment_reminder.create.inserted",
        extra={
            "payment_reminder_id": getattr(reminder, "id", None),
            "account": _mask(cuenta),
            "session_id": session_id,
            "status": reminder.status,
            "scheduled_for": reminder.scheduled_for.isoformat() if reminder.scheduled_for else None,
            "reminder_type": reminder.reminder_type,
            "skip_reason": canonical_reason,
        },
    )
    return reminder


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


def _claim_due_payment_reminder(db: Session, *, reminder: PaymentReminder, now: datetime) -> bool:
    updated = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.id == reminder.id)
        .filter(PaymentReminder.status == STATUS_SCHEDULED)
        .filter(PaymentReminder.scheduled_for <= now)
        .update(
            {
                PaymentReminder.status: STATUS_PROCESSING,
                PaymentReminder.updated_at: now,
                PaymentReminder.error_code: None,
                PaymentReminder.error_message_sanitized: None,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        logger.info(
            "payment_reminder.duplicate.prevented",
            extra={
                "payment_reminder_id": getattr(reminder, "id", None),
                "account": _mask(getattr(reminder, "cuenta", None)),
                "existing_status": getattr(reminder, "status", None),
                "reason": "claim_failed",
            },
        )
        return False
    db.commit()
    reminder.status = STATUS_PROCESSING
    if hasattr(db, "refresh"):
        db.refresh(reminder)
    return True


def _last_sent_payment_reminder(
    db: Session,
    *,
    cuenta: str | None = None,
    session_id: int | None = None,
    exclude_id: int | None = None,
) -> PaymentReminder | None:
    if not cuenta and not session_id:
        return None
    query = db.query(PaymentReminder).filter(PaymentReminder.status == STATUS_SENT)
    filters = []
    if cuenta:
        filters.append(PaymentReminder.cuenta == cuenta)
    if session_id:
        filters.append(PaymentReminder.session_id == session_id)
    query = query.filter(or_(*filters) if len(filters) > 1 else filters[0])
    if exclude_id:
        query = query.filter(PaymentReminder.id != exclude_id)
    return query.order_by(PaymentReminder.sent_at.desc(), PaymentReminder.id.desc()).first()


def _last_sent_payment_message(
    db: Session,
    *,
    session_id: int | None = None,
) -> Message | None:
    if not session_id:
        return None
    return (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .filter(Message.direction == "out")
        .filter(Message.type == "payment_reminder")
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )


def _sent_reference_at(record: Any) -> datetime | None:
    return getattr(record, "sent_at", None) or getattr(record, "created_at", None)


def _next_allowed_send_at(last_sent_at: datetime | None) -> datetime | None:
    if not last_sent_at:
        return None
    return last_sent_at + timedelta(days=PAYMENT_REMINDER_MIN_INTERVAL_DAYS)


def _weekly_frequency_blocked(
    db: Session,
    *,
    cuenta: str | None,
    session_id: int | None,
    now: datetime | None = None,
    exclude_id: int | None = None,
) -> tuple[bool, Any | None, datetime | None]:
    last_reminder = _last_sent_payment_reminder(
        db,
        cuenta=cuenta,
        session_id=session_id,
        exclude_id=exclude_id,
    )
    last_message = _last_sent_payment_message(db, session_id=session_id)
    candidates = [
        candidate
        for candidate in (last_reminder, last_message)
        if _sent_reference_at(candidate)
    ]
    last_sent = max(candidates, key=lambda candidate: _sent_reference_at(candidate), default=None)
    next_allowed = _next_allowed_send_at(_sent_reference_at(last_sent))
    now = now or mexico_now_naive()
    return bool(next_allowed and now < next_allowed), last_sent, next_allowed


def _scheduled_datetime_for_next_week(schedule: PaymentSchedule, *, last_sent_at: datetime | None = None) -> datetime:
    scheduled = _scheduled_datetime(schedule.next_due_date)
    next_allowed = _next_allowed_send_at(last_sent_at)
    if next_allowed and scheduled < next_allowed:
        return next_allowed
    return scheduled


def _next_reminder_schedule_after_send(
    *,
    sent_at: datetime,
    previous_schedule: PaymentSchedule,
) -> tuple[PaymentSchedule, datetime]:
    next_scheduled_for = sent_at + timedelta(days=PAYMENT_REMINDER_MIN_INTERVAL_DAYS)
    next_due = next_scheduled_for.date()
    return (
        PaymentSchedule(
            due_date=next_due,
            next_due_date=next_due + timedelta(days=PAYMENT_REMINDER_MIN_INTERVAL_DAYS),
            weekday=next_due.weekday(),
            source="last_reminder_sent_at_plus_7",
            base_date=sent_at.date(),
            base_date_source="payment_reminder_sent_at",
        ),
        next_scheduled_for,
    )


def _reschedule_after_weekly_block(
    reminder: PaymentReminder,
    *,
    schedule: PaymentSchedule,
    next_allowed_at: datetime,
) -> None:
    next_due = schedule.next_due_date
    if next_allowed_at.date() > next_due:
        next_due = next_allowed_at.date()
    reminder.due_date = next_due
    reminder.next_due_date = next_due + timedelta(days=7)
    reminder.scheduled_for = max(_scheduled_datetime(next_due), next_allowed_at)
    reminder.status = STATUS_SCHEDULED
    reminder.error_code = REASON_WEEKLY_FREQUENCY_BLOCKED
    reminder.error_message_sanitized = (
        f"next_allowed_payment_reminder_at:{next_allowed_at.isoformat()}"
    )[:255]
    reminder.updated_at = mexico_now_naive()


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
        last_sent_row = max(
            (row for row in sent_rows if row.sent_at),
            key=lambda row: row.sent_at,
            default=None,
        )
        next_scheduled_row = min(
            (row for row in scheduled_rows if row.scheduled_for),
            key=lambda row: row.scheduled_for,
            default=None,
        )
        last_message = _last_sent_payment_message(db, session_id=session_id)
        last_message_at = _sent_reference_at(last_message)
        last_reminder_at = _sent_reference_at(last_sent_row)
        if last_message and last_message_at and (not last_reminder_at or last_message_at > last_reminder_at):
            last_sent_at = _sent_reference_at(last_message)
            last_sent_id = None
        else:
            last_sent_at = last_reminder_at
            last_sent_id = getattr(last_sent_row, "id", None)
        return ReminderStats(
            sent_count=len(sent_rows),
            last_sent_at=last_sent_at,
            last_sent_reminder_id=last_sent_id,
            next_scheduled_at=getattr(next_scheduled_row, "scheduled_for", None),
            existing_scheduled_id=getattr(next_scheduled_row, "id", None),
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
    template_name: str | None = None,
    sent_at: datetime | None = None,
) -> str:
    cuenta = snapshot.account_reference_formatted or format_account_reference(snapshot.cuenta) or snapshot.cuenta or "N/D"
    minimum = _money_text(snapshot.minimum_payment)
    balance = _money_text(snapshot.balance)
    due = _date_text(schedule.due_date if schedule else None)
    sent_text = (sent_at or mexico_now_naive()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "Recordatorio de pago enviado.",
        f"Cuenta: {cuenta}",
    ]
    if snapshot.folio:
        lines.append(f"Folio: {snapshot.folio}")
    lines.extend(
        [
            f"Fecha de vencimiento: {due}",
            f"Fecha de envio: {sent_text}",
            f"Telefono: {_mask(snapshot.phone)}",
            f"Plantilla: {template_name or 'N/D'}",
            f"Monto minimo: {minimum}",
            f"Saldo: {balance}",
        ]
    )
    return "\n".join(lines)


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
    base_should_send = bool(
        template_name
        and snapshot.payment_status == PAYMENT_STATUS_UNPAID
        and cuenta_formateada_valida
        and classification not in {CLASS_NOT_DUE, CLASS_SETTLED, CLASS_BRIDGE_ERROR, CLASS_INSUFFICIENT_BRIDGE_DATA}
        and (session_resolution is None or session_resolution.found)
    )
    session_found = bool(session_resolution.found) if session_resolution else None
    session_id = session_resolution.session_id if session_resolution else None
    stats = reminder_stats or ReminderStats()
    test_mode = payment_reminders_test_mode_enabled()
    test_phone_allowed = payment_reminder_test_phone_allowed(snapshot.phone)
    next_allowed = _next_allowed_send_at(stats.last_sent_at)
    now = mexico_now_naive()
    weekly_frequency_allowed = not next_allowed or now >= next_allowed
    effective_reason = reason
    if base_should_send and not test_phone_allowed:
        effective_reason = REASON_TEST_PHONE_NOT_ALLOWED
    elif base_should_send and not weekly_frequency_allowed:
        effective_reason = REASON_WEEKLY_FREQUENCY_BLOCKED
    should_send = bool(base_should_send and test_phone_allowed and weekly_frequency_allowed)
    preview = (
        _build_conversation_message_preview(
            snapshot=snapshot,
            schedule=schedule,
            template_name=template_name,
        )
        if schedule
        else None
    )
    return {
        "cuenta": snapshot.cuenta,
        "folio": snapshot.folio,
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
        "reason": effective_reason,
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
        "test_mode": test_mode,
        "test_phone_allowed": test_phone_allowed,
        "test_phone_configured_count": len(_configured_test_phones()) if test_mode else None,
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
        "existing_scheduled_reminder_id": stats.existing_scheduled_id,
        "duplicate_prevented": classification in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT, CLASS_ALREADY_TERMINAL},
        "sent_count_prev": stats.sent_count,
        "last_payment_reminder_at": stats.last_sent_at.isoformat() if stats.last_sent_at else None,
        "last_payment_reminder_id": stats.last_sent_reminder_id,
        "weekly_frequency_allowed": weekly_frequency_allowed,
        "next_allowed_payment_reminder_at": next_allowed.isoformat() if next_allowed else None,
    }


def _canonical_omission_reason(classification: str | None, reason: str | None) -> str | None:
    if reason in OMISSION_REASONS:
        return reason
    if classification in OMISSION_REASONS:
        return classification
    if classification == CLASS_SETTLED or reason == "settled_confirmed_by_bridge":
        return REASON_PAID_OR_SETTLED
    if classification == CLASS_INSUFFICIENT_BRIDGE_DATA:
        return REASON_MISSING_BRIDGE_FIELDS
    if reason in {"missing_bridge_payment_base_date", "invalid_default_weekday"}:
        return REASON_MISSING_BRIDGE_FIELDS
    return None


def _log_payment_reminder_omission(
    *,
    source: str,
    result: Mapping[str, Any],
    extra_fields: Mapping[str, Any] | None = None,
) -> None:
    reason = _canonical_omission_reason(
        str(result.get("classification") or ""),
        str(result.get("reason") or ""),
    )
    if not reason:
        return
    payload = {
        "source": source,
        "reason": reason,
        "classification": result.get("classification"),
        "cuenta_masked": _mask(result.get("cuenta") or result.get("cuenta_formateada")),
        "folio_masked": _mask(result.get("folio")),
        "phone_masked": result.get("phone_masked"),
        "session_id": result.get("session_id"),
        "template_name": result.get("template_name"),
        "reminder_type": result.get("reminder_type"),
        "missing_fields": result.get("missing_fields") or [],
    }
    if extra_fields:
        payload.update(dict(extra_fields))
    logger.info("payment_reminder_omitted", extra=payload)


def _reason_counts(results: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        reason = _canonical_omission_reason(
            str(result.get("classification") or ""),
            str(result.get("reason") or ""),
        )
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


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
            reason=REASON_PAID_OR_SETTLED,
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
            reason=REASON_MISSING_BRIDGE_FIELDS,
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
            reason=REASON_MISSING_BRIDGE_FIELDS,
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
            reason=REASON_PAID_OR_SETTLED,
        )
        if not dry_run:
            reminder.bridge_found = snapshot.bridge_found
            reminder.bridge_snapshot_hash = snapshot.snapshot_hash
            reminder.saldo_snapshot = snapshot.balance
            reminder.monto_minimo_snapshot = snapshot.minimum_payment
            _mark_result(reminder, status=STATUS_CANCELLED_SETTLED)
            if snapshot.cuenta:
                cancelled_count = _cancel_future_settled(db, cuenta=snapshot.cuenta, current_id=reminder.id)
                logger.info(
                    "payment_reminder.cancelled_settled",
                    extra={
                        "reminder_id": getattr(reminder, "id", None),
                        "account": _mask(snapshot.cuenta),
                        "cancelled_count": cancelled_count,
                        "reason": REASON_PAID_OR_SETTLED,
                    },
                )
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
            reason=REASON_MISSING_BRIDGE_FIELDS,
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
            reason=REASON_MISSING_BRIDGE_FIELDS,
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
        cancelled_count = _cancel_future_settled(db, cuenta=snapshot.cuenta, current_id=reminder.id)
        logger.info(
            "payment_reminder.cancelled_settled",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "cancelled_count": cancelled_count,
                "reason": REASON_PAID_OR_SETTLED,
            },
        )
        result["reason"] = REASON_PAID_OR_SETTLED
        return result

    if not payment_reminder_test_phone_allowed(snapshot.phone):
        _mark_result(
            reminder,
            status=STATUS_SKIPPED,
            error_code=REASON_TEST_PHONE_NOT_ALLOWED,
            error_message=REASON_TEST_PHONE_NOT_ALLOWED,
        )
        logger.info(
            "payment_reminder.test_mode.blocked",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "phone_masked": _mask(snapshot.phone),
                "test_phone_configured_count": len(_configured_test_phones()),
            },
        )
        result["reason"] = REASON_TEST_PHONE_NOT_ALLOWED
        result["should_send"] = False
        result["would_send"] = False
        result["would_create_conversation_message"] = False
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
            error_code=REASON_TEMPLATE_MISSING,
            error_message="meta_template_not_configured",
        )
        result["reason"] = REASON_TEMPLATE_MISSING
        return result

    blocked, last_sent, next_allowed = _weekly_frequency_blocked(
        db,
        cuenta=snapshot.cuenta,
        session_id=session_resolution.session_id,
        exclude_id=getattr(reminder, "id", None),
    )
    if blocked and next_allowed:
        _reschedule_after_weekly_block(
            reminder,
            schedule=schedule,
            next_allowed_at=next_allowed,
        )
        logger.info(
            "payment_reminder.weekly_frequency.blocked",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "session_id": session_resolution.session_id,
                "last_sent_at": _sent_reference_at(last_sent).isoformat() if _sent_reference_at(last_sent) else None,
                "next_allowed_at": next_allowed.isoformat(),
            },
        )
        result["reason"] = REASON_WEEKLY_FREQUENCY_BLOCKED
        result["should_send"] = False
        result["would_send"] = False
        result["would_create_conversation_message"] = False
        result["next_allowed_payment_reminder_at"] = next_allowed.isoformat()
        result["scheduled_at"] = reminder.scheduled_for.isoformat() if reminder.scheduled_for else None
        result["due_date"] = reminder.due_date.isoformat() if reminder.due_date else result.get("due_date")
        result["next_due_date"] = reminder.next_due_date.isoformat() if reminder.next_due_date else result.get("next_due_date")
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

    parameters = build_template_parameters(
        reminder_type=reminder_type,
        snapshot=snapshot,
        schedule=schedule,
    )
    logger.info(
        "payment_reminder.send.attempt",
        extra={
            "reminder_id": getattr(reminder, "id", None),
            "account": _mask(snapshot.cuenta),
            "phone_masked": _mask(snapshot.phone),
            "template_name": template_name,
            "reminder_type": reminder_type,
        },
    )
    try:
        response = await send_template_message(
            snapshot.phone,
            template_name,
            parameters,
            language=settings.META_TEMPLATE_LANGUAGE,
        )
    except Exception as exc:
        _mark_result(
            reminder,
            status=STATUS_FAILED,
            error_code=REASON_META_ERROR,
            error_message=exc.__class__.__name__,
        )
        logger.exception(
            "payment_reminder_meta_error",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "cuenta_masked": _mask(snapshot.cuenta),
                "phone_last4": _mask(snapshot.phone),
                "template_name": template_name,
                "error_type": exc.__class__.__name__,
            },
        )
        logger.warning(
            "payment_reminder.send.failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "phone_masked": _mask(snapshot.phone),
                "template_name": template_name,
                "error_type": exc.__class__.__name__,
                "skip_reason": REASON_META_ERROR,
            },
        )
        result["reason"] = REASON_META_ERROR
        return result
    status_code = getattr(response, "status_code", None)
    if response is None or (status_code is not None and status_code >= 400):
        _mark_result(
            reminder,
            status=STATUS_FAILED,
            error_code=REASON_META_ERROR,
            error_message=f"meta_status_{status_code or 'none'}",
        )
        logger.warning(
            "payment_reminder.send.failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "phone_masked": _mask(snapshot.phone),
                "template_name": template_name,
                "http_status": status_code,
                "skip_reason": REASON_META_ERROR,
            },
        )
        result["reason"] = REASON_META_ERROR
        return result

    reminder.reminder_type = reminder_type
    reminder.meta_message_id = _response_meta_message_id(response)
    _mark_result(reminder, status=STATUS_SENT)
    logger.info(
        "payment_reminder.send.accepted",
        extra={
            "reminder_id": getattr(reminder, "id", None),
            "account": _mask(snapshot.cuenta),
            "phone_masked": _mask(snapshot.phone),
            "template_name": template_name,
            "meta_message_id": reminder.meta_message_id,
        },
    )
    result["conversation_message_created"] = False
    try:
        message_context = db.begin_nested() if hasattr(db, "begin_nested") else nullcontext()
        with message_context:
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
    except Exception as exc:
        _mark_result(
            reminder,
            status=STATUS_SENT,
            error_code=REASON_MESSAGE_INSERT_FAILED,
            error_message=exc.__class__.__name__,
        )
        logger.exception(
            "payment_reminder_conversation_message_failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "session_id": session_resolution.session_id,
                "cuenta_masked": _mask(snapshot.cuenta),
                "error_type": exc.__class__.__name__,
            },
        )
        logger.exception(
            "payment_reminder.message.failed",
            extra={
                "reminder_id": getattr(reminder, "id", None),
                "session_id": session_resolution.session_id,
                "account": _mask(snapshot.cuenta),
                "error_type": exc.__class__.__name__,
            },
        )
        result["conversation_message_error"] = REASON_MESSAGE_INSERT_FAILED

    chat_session = session_resolution.session
    if chat_session and chat_session.status != "COBRANZA":
        chat_session.status = "COBRANZA"
        db.add(chat_session)
        # db.commit() is usually handled by the caller transaction

    next_template, next_type = _template_for_classification(CLASS_NOT_DUE)
    next_schedule, next_scheduled_for = _next_reminder_schedule_after_send(
        sent_at=reminder.sent_at or mexico_now_naive(),
        previous_schedule=schedule,
    )
    next_reminder, next_status = upsert_scheduled_reminder(
        db,
        snapshot=snapshot,
        schedule=next_schedule,
        reminder_type=next_type or REMINDER_PAYMENT_PENDING,
        template_name=next_template,
        session_id=session_resolution.session_id,
    )
    if next_reminder is not None and next_status in {STATUS_SCHEDULED, CLASS_ALREADY_SCHEDULED}:
        next_reminder.due_date = next_schedule.due_date
        next_reminder.next_due_date = next_schedule.next_due_date
        next_reminder.scheduled_for = next_scheduled_for
        logger.info(
            "payment_reminder.next_scheduled",
            extra={
                "current_reminder_id": getattr(reminder, "id", None),
                "next_reminder_id": getattr(next_reminder, "id", None),
                "account": _mask(snapshot.cuenta),
                "session_id": session_resolution.session_id,
                "due_date": next_reminder.due_date.isoformat() if next_reminder.due_date else None,
                "scheduled_for": next_reminder.scheduled_for.isoformat() if next_reminder.scheduled_for else None,
                "status": next_status,
            },
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
    company_id = int(company_id or settings.PAYMENT_REMINDER_COMPANY_ID)
    dry_run_effective = settings.PAYMENT_REMINDERS_DRY_RUN if dry_run is None else bool(dry_run)
    reminders = (
        db.query(PaymentReminder)
        .filter(PaymentReminder.status.in_(list(ACTIVE_REMINDER_STATUSES)))
        .filter(PaymentReminder.scheduled_for <= now)
        .order_by(PaymentReminder.scheduled_for.asc(), PaymentReminder.id.asc())
        .limit(limit)
        .all()
    )
    logger.info(
        "payment_reminders_run_due_started",
        extra={
            "company_id": company_id,
            "dry_run": dry_run_effective,
            "due_count": len(reminders),
            "limit": limit,
            "now": now.isoformat(),
        },
    )
    results = []
    for reminder in reminders:
        claimed = False
        try:
            if not dry_run_effective:
                claimed = _claim_due_payment_reminder(db, reminder=reminder, now=now)
                if not claimed:
                    continue
            result = await process_due_payment_reminder(
                db,
                reminder,
                company_id=company_id,
                client=client,
                dry_run=dry_run,
            )
            results.append(result)
            _log_payment_reminder_omission(
                source="run_due",
                result=result,
                extra_fields={"reminder_id": getattr(reminder, "id", None)},
            )
            if not dry_run_effective:
                db.commit()
        except Exception as exc:
            db.rollback()
            if claimed:
                try:
                    failed = db.query(PaymentReminder).filter(PaymentReminder.id == reminder.id).first()
                    if failed is not None:
                        _mark_result(
                            failed,
                            status=STATUS_FAILED,
                            error_code="processing_exception",
                            error_message=exc.__class__.__name__,
                        )
                        db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "payment_reminder_processing_failure_mark_failed",
                        extra={
                            "reminder_id": getattr(reminder, "id", None),
                            "cuenta_masked": _mask(getattr(reminder, "cuenta", None)),
                        },
                    )
            logger.exception(
                "payment_reminder_processing_exception",
                extra={
                    "reminder_id": reminder.id,
                    "cuenta_masked": _mask(reminder.cuenta),
                    "error_type": exc.__class__.__name__,
                },
            )
            results.append(
                {
                    "payment_reminder_id": getattr(reminder, "id", None),
                    "cuenta": getattr(reminder, "cuenta", None),
                    "reason": "processing_exception",
                    "error_type": exc.__class__.__name__,
                }
            )
    counts = _reason_counts(results)
    logger.info(
        "payment_reminders_run_due_finished",
        extra={
            "company_id": company_id,
            "dry_run": dry_run_effective,
            "due_count": len(reminders),
            "processed": len(results),
            "sent": sum(1 for result in results if result.get("reason") == "sent"),
            "reason_counts": counts,
        },
    )
    return {
        "processed": len(results),
        "due_count": len(reminders),
        "reason_counts": counts,
        "results": results,
    }


async def sync_payment_reminder_candidates(
    db: Session,
    *,
    company_id: int | None = None,
    limit: int | None = None,
    dry_run: bool | None = None,
    cuenta: str | None = None,
    folio: str | None = None,
    client: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    company_id = int(company_id or settings.PAYMENT_REMINDER_COMPANY_ID)
    limit = int(limit or settings.PAYMENT_REMINDER_SYNC_LIMIT or 100)
    dry_run = settings.PAYMENT_REMINDERS_DRY_RUN if dry_run is None else bool(dry_run)
    today = today or mexico_now_naive().date()
    client = client or get_siga_bridge_client()

    results = []

    def add_result(
        result: dict[str, Any],
        *,
        snapshot: BridgeAccountSnapshot | None = None,
        schedule: PaymentSchedule | None = None,
        source: str = "sync",
        audit: bool = False,
    ) -> dict[str, Any]:
        if audit and snapshot is not None:
            audit_row = record_payment_reminder_audit(
                db,
                snapshot=snapshot,
                schedule=schedule,
                classification=str(result.get("classification") or ""),
                reason=str(result.get("reason") or ""),
                reminder_type=result.get("reminder_type"),
                template_name=result.get("template_name"),
                session_id=result.get("session_id"),
                dry_run=dry_run,
            )
            if audit_row is not None:
                result["payment_reminder_id"] = getattr(audit_row, "id", None)
                result["audited"] = True
        results.append(result)
        _log_payment_reminder_omission(source=source, result=result)
        return result

    def build_single_result(
        *,
        snapshot: BridgeAccountSnapshot,
        session_resolution: ChatSessionResolution,
        stats: ReminderStats,
        schedule: PaymentSchedule | None,
        classification: str,
        template_name: str | None,
        reminder_type: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        return _build_process_result(
            snapshot=snapshot,
            schedule=schedule,
            classification=classification,
            template_name=template_name,
            reminder_type=reminder_type,
            dry_run=dry_run,
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason=reason,
        )

    if cuenta or folio:
        logger.info(
            "payment_reminder_candidate_sync_started",
            extra={
                "company_id": company_id,
                "dry_run": dry_run,
                "limit": 1,
                "source": "single_account",
                "account": _mask(cuenta),
                "folio_masked": _mask(folio),
                "chat_sessions_scanned": 0,
                "scan_limit": 0,
            },
        )
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

        try:
            if snapshot.error_code:
                add_result(
                    build_single_result(
                        snapshot=snapshot,
                        session_resolution=session_resolution,
                        stats=stats,
                        schedule=None,
                        classification=CLASS_BRIDGE_ERROR,
                        template_name=None,
                        reminder_type=None,
                        reason=snapshot.error_message_sanitized or snapshot.error_code,
                    ),
                    snapshot=snapshot,
                    source="sync_account",
                    audit=True,
                )
            elif snapshot.settled:
                cancelled_count = 0
                if not dry_run and snapshot.cuenta:
                    cancelled_count = _cancel_future_settled(db, cuenta=snapshot.cuenta)
                    logger.info(
                        "payment_reminder.cancelled_settled",
                        extra={
                            "account": _mask(snapshot.cuenta),
                            "cancelled_count": cancelled_count,
                            "reason": REASON_PAID_OR_SETTLED,
                            "source": "sync_account",
                        },
                    )
                result = build_single_result(
                    snapshot=snapshot,
                    session_resolution=session_resolution,
                    stats=stats,
                    schedule=None,
                    classification=CLASS_SETTLED,
                    template_name=None,
                    reminder_type=None,
                    reason=REASON_PAID_OR_SETTLED,
                )
                result["cancelled_count"] = cancelled_count
                add_result(result, snapshot=snapshot, source="sync_account", audit=True)
            elif snapshot.missing_fields:
                add_result(
                    build_single_result(
                        snapshot=snapshot,
                        session_resolution=session_resolution,
                        stats=stats,
                        schedule=None,
                        classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                        template_name=None,
                        reminder_type=None,
                        reason=REASON_MISSING_BRIDGE_FIELDS,
                    ),
                    snapshot=snapshot,
                    source="sync_account",
                    audit=True,
                )
            elif not session_resolution.found:
                add_result(
                    build_single_result(
                        snapshot=snapshot,
                        session_resolution=session_resolution,
                        stats=stats,
                        schedule=None,
                        classification=session_resolution.reason,
                        template_name=None,
                        reminder_type=None,
                        reason=session_resolution.reason,
                    ),
                    snapshot=snapshot,
                    source="sync_account",
                    audit=True,
                )
            else:
                try:
                    schedule = calculate_snapshot_due_schedule(snapshot, today=today)
                except PaymentScheduleError as exc:
                    add_result(
                        build_single_result(
                            snapshot=snapshot,
                            session_resolution=session_resolution,
                            stats=stats,
                            schedule=None,
                            classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                            template_name=None,
                            reminder_type=None,
                            reason=str(exc),
                        ),
                        snapshot=snapshot,
                        source="sync_account",
                        audit=True,
                    )
                else:
                    classification = classify_reminder_case(
                        bridge_found=snapshot.bridge_found,
                        missing_fields=snapshot.missing_fields,
                        payment_status=snapshot.payment_status,
                        due_date=schedule.due_date,
                        today=today,
                    )
                    template_name, reminder_type = _template_for_classification(classification)
                    if not payment_reminder_test_phone_allowed(snapshot.phone):
                        logger.info(
                            "payment_reminder.test_mode.blocked",
                            extra={
                                "account": _mask(snapshot.cuenta),
                                "phone_masked": _mask(snapshot.phone),
                                "session_id": session_resolution.session_id,
                                "source": "sync_account",
                                "test_phone_configured_count": len(_configured_test_phones()),
                            },
                        )
                        add_result(
                            build_single_result(
                                snapshot=snapshot,
                                session_resolution=session_resolution,
                                stats=stats,
                                schedule=schedule,
                                classification=classification,
                                template_name=template_name,
                                reminder_type=reminder_type,
                                reason=REASON_TEST_PHONE_NOT_ALLOWED,
                            ),
                            snapshot=snapshot,
                            schedule=schedule,
                            source="sync_account",
                            audit=True,
                        )
                    elif classification in {CLASS_DUE_TODAY_UNPAID, CLASS_OVERDUE_UNPAID}:
                        blocked, last_sent, next_allowed = _weekly_frequency_blocked(
                            db,
                            cuenta=snapshot.cuenta,
                            session_id=session_resolution.session_id,
                        )
                        if blocked and next_allowed:
                            logger.info(
                                "payment_reminder.weekly_frequency.blocked",
                                extra={
                                    "account": _mask(snapshot.cuenta),
                                    "session_id": session_resolution.session_id,
                                    "source": "sync_account",
                                    "last_sent_at": _sent_reference_at(last_sent).isoformat() if _sent_reference_at(last_sent) else None,
                                    "next_allowed_at": next_allowed.isoformat(),
                                },
                            )
                            add_result(
                                build_single_result(
                                    snapshot=snapshot,
                                    session_resolution=session_resolution,
                                    stats=stats,
                                    schedule=schedule,
                                    classification=classification,
                                    template_name=template_name,
                                    reminder_type=reminder_type,
                                    reason=REASON_WEEKLY_FREQUENCY_BLOCKED,
                                ),
                                snapshot=snapshot,
                                schedule=schedule,
                                source="sync_account",
                                audit=True,
                            )
                        elif not template_name:
                            add_result(
                                build_single_result(
                                    snapshot=snapshot,
                                    session_resolution=session_resolution,
                                    stats=stats,
                                    schedule=schedule,
                                    classification=classification,
                                    template_name=None,
                                    reminder_type=reminder_type,
                                    reason=REASON_TEMPLATE_MISSING,
                                ),
                                snapshot=snapshot,
                                schedule=schedule,
                                source="sync_account",
                                audit=True,
                            )
                        else:
                            if not reminder_type:
                                reminder_type = REMINDER_PAYMENT_PENDING
                            logger.info(
                                "payment_reminder.create.insert.start",
                                extra={
                                    "account": _mask(snapshot.cuenta),
                                    "session_id": session_resolution.session_id,
                                    "status": STATUS_SCHEDULED,
                                    "scheduled_for": _scheduled_datetime(schedule.due_date).isoformat(),
                                    "reminder_type": reminder_type,
                                },
                            )
                            reminder, status = upsert_scheduled_reminder(
                                db,
                                snapshot=snapshot,
                                schedule=schedule,
                                reminder_type=reminder_type,
                                template_name=template_name,
                                session_id=session_resolution.session_id,
                                dry_run=dry_run,
                            )
                            if reminder is not None and stats.last_sent_at:
                                next_allowed = _next_allowed_send_at(stats.last_sent_at)
                                if next_allowed and reminder.scheduled_for and reminder.scheduled_for < next_allowed:
                                    reminder.scheduled_for = next_allowed
                            result = build_single_result(
                                snapshot=snapshot,
                                session_resolution=session_resolution,
                                stats=stats,
                                schedule=schedule,
                                classification=status if status in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT, CLASS_ALREADY_TERMINAL} else classification,
                                template_name=template_name,
                                reminder_type=reminder_type,
                                reason=status,
                            )
                            if reminder is not None:
                                result["payment_reminder_id"] = getattr(reminder, "id", None)
                            add_result(result, snapshot=snapshot, schedule=schedule, source="sync_account")
                    else:
                        if not reminder_type:
                            reminder_type = REMINDER_PAYMENT_PENDING
                        logger.info(
                            "payment_reminder.create.insert.start",
                            extra={
                                "account": _mask(snapshot.cuenta),
                                "session_id": session_resolution.session_id,
                                "status": STATUS_SCHEDULED,
                                "scheduled_for": _scheduled_datetime(schedule.due_date).isoformat(),
                                "reminder_type": reminder_type,
                            },
                        )
                        reminder, status = upsert_scheduled_reminder(
                            db,
                            snapshot=snapshot,
                            schedule=schedule,
                            reminder_type=reminder_type,
                            template_name=template_name,
                            session_id=session_resolution.session_id,
                            dry_run=dry_run,
                        )
                        if reminder is not None and stats.last_sent_at:
                            next_allowed = _next_allowed_send_at(stats.last_sent_at)
                            if next_allowed and reminder.scheduled_for and reminder.scheduled_for < next_allowed:
                                reminder.scheduled_for = next_allowed
                        result = build_single_result(
                            snapshot=snapshot,
                            session_resolution=session_resolution,
                            stats=stats,
                            schedule=schedule,
                            classification=status if status in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT, CLASS_ALREADY_TERMINAL} else classification,
                            template_name=template_name,
                            reminder_type=reminder_type,
                            reason=status,
                        )
                        if reminder is not None:
                            result["payment_reminder_id"] = getattr(reminder, "id", None)
                        add_result(result, snapshot=snapshot, schedule=schedule, source="sync_account")

            if not dry_run:
                db.commit()
                logger.info(
                    "payment_reminder.create.commit.ok",
                    extra={
                        "company_id": company_id,
                        "account": _mask(snapshot.cuenta or cuenta),
                        "source": "sync_account",
                        "synced": len(results),
                    },
                )
        except Exception as exc:
            if not dry_run:
                db.rollback()
            logger.exception(
                "payment_reminder.create.failed",
                extra={
                    "company_id": company_id,
                    "account": _mask(snapshot.cuenta or cuenta),
                    "source": "sync_account",
                    "error_type": exc.__class__.__name__,
                },
            )
            raise

        counts = _reason_counts(results)
        logger.info(
            "payment_reminder_candidate_sync_finished",
            extra={
                "company_id": company_id,
                "dry_run": dry_run,
                "source": "single_account",
                "chat_sessions_scanned": 0,
                "chat_sessions_with_context": 1,
                "synced": len(results),
                "reason_counts": counts,
            },
        )
        return {
            "synced": len(results),
            "chat_sessions_scanned": 0,
            "chat_sessions_with_context": 1,
            "reason_counts": counts,
            "source": "single_account",
            "results": results,
        }

    scan_limit = max(limit * 20, 250)
    sessions = _chat_session_payment_candidates(db, limit=scan_limit)
    sessions_with_context = 0
    logger.info(
        "payment_reminder_candidate_sync_started",
        extra={
            "company_id": company_id,
            "dry_run": dry_run,
            "limit": limit,
            "chat_sessions_scanned": len(sessions),
            "scan_limit": scan_limit,
        },
    )

    for session in sessions:
        if len(results) >= limit:
            break

        session_cuenta = _session_account_candidate(session)
        session_folio = _session_folio_candidate(session)
        if not session_cuenta and not session_folio:
            logger.info(
                "payment_reminder_omitted",
                extra={
                    "source": "sync",
                    "reason": REASON_MISSING_BRIDGE_FIELDS,
                    "session_id": getattr(session, "id", None),
                    "phone_masked": _mask(getattr(session, "phone", None)),
                    "missing_fields": ["folio_or_cuenta"],
                },
            )
            continue
        sessions_with_context += 1

        snapshot = await fetch_bridge_account_snapshot(
            cuenta=session_cuenta,
            folio=session_folio,
            company_id=company_id,
            client=client,
        )
        session_resolution = resolve_chat_session_for_reminder(
            db,
            snapshot=snapshot,
            phone=snapshot.phone or getattr(session, "phone", None),
            folio=snapshot.folio or session_folio,
            cuenta=snapshot.account_reference_formatted or snapshot.cuenta or session_cuenta,
            session_id=getattr(session, "id", None),
        )
        stats = _reminder_stats(
            db,
            cuenta=snapshot.cuenta or session_cuenta,
            session_id=session_resolution.session_id,
        )
        if snapshot.error_code:
            add_result(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_BRIDGE_ERROR,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=snapshot.error_message_sanitized or snapshot.error_code,
                ),
                snapshot=snapshot,
                audit=True,
            )
            continue
        if snapshot.settled:
            if not dry_run and snapshot.cuenta:
                cancelled_count = _cancel_future_settled(db, cuenta=snapshot.cuenta)
                logger.info(
                    "payment_reminder.cancelled_settled",
                    extra={
                        "account": _mask(snapshot.cuenta),
                        "cancelled_count": cancelled_count,
                        "reason": REASON_PAID_OR_SETTLED,
                        "source": "sync",
                    },
                )
            add_result(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_SETTLED,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=REASON_PAID_OR_SETTLED,
                ),
                snapshot=snapshot,
                audit=True,
            )
            continue
        if snapshot.missing_fields:
            add_result(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=REASON_MISSING_BRIDGE_FIELDS,
                ),
                snapshot=snapshot,
                audit=True,
            )
            continue

        if not session_resolution.found:
            add_result(
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
                ),
                snapshot=snapshot,
                audit=True,
            )
            continue

        try:
            schedule = calculate_snapshot_due_schedule(snapshot, today=today)
        except PaymentScheduleError as exc:
            add_result(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=None,
                    classification=CLASS_INSUFFICIENT_BRIDGE_DATA,
                    template_name=None,
                    reminder_type=None,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=REASON_MISSING_BRIDGE_FIELDS,
                ),
                snapshot=snapshot,
                audit=True,
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
        if not payment_reminder_test_phone_allowed(snapshot.phone):
            logger.info(
                "payment_reminder.test_mode.blocked",
                extra={
                    "account": _mask(snapshot.cuenta),
                    "phone_masked": _mask(snapshot.phone),
                    "session_id": session_resolution.session_id,
                    "source": "sync",
                    "test_phone_configured_count": len(_configured_test_phones()),
                },
            )
            add_result(
                _build_process_result(
                    snapshot=snapshot,
                    schedule=schedule,
                    classification=classification,
                    template_name=template_name,
                    reminder_type=reminder_type,
                    dry_run=dry_run,
                    session_resolution=session_resolution,
                    reminder_stats=stats,
                    reason=REASON_TEST_PHONE_NOT_ALLOWED,
                ),
                snapshot=snapshot,
                schedule=schedule,
                audit=True,
            )
            continue
        if classification in {CLASS_DUE_TODAY_UNPAID, CLASS_OVERDUE_UNPAID}:
            blocked, last_sent, next_allowed = _weekly_frequency_blocked(
                db,
                cuenta=snapshot.cuenta,
                session_id=session_resolution.session_id,
            )
            if blocked and next_allowed:
                logger.info(
                    "payment_reminder.weekly_frequency.blocked",
                    extra={
                        "account": _mask(snapshot.cuenta),
                        "session_id": session_resolution.session_id,
                        "source": "sync",
                        "last_sent_at": _sent_reference_at(last_sent).isoformat() if _sent_reference_at(last_sent) else None,
                        "next_allowed_at": next_allowed.isoformat(),
                    },
                )
                add_result(
                    _build_process_result(
                        snapshot=snapshot,
                        schedule=schedule,
                        classification=classification,
                        template_name=template_name,
                        reminder_type=reminder_type,
                        dry_run=dry_run,
                        session_resolution=session_resolution,
                        reminder_stats=stats,
                        reason=REASON_WEEKLY_FREQUENCY_BLOCKED,
                    ),
                    snapshot=snapshot,
                    schedule=schedule,
                    audit=True,
                )
                continue
            if not template_name:
                add_result(
                    _build_process_result(
                        snapshot=snapshot,
                        schedule=schedule,
                        classification=classification,
                        template_name=None,
                        reminder_type=reminder_type,
                        dry_run=dry_run,
                        session_resolution=session_resolution,
                        reminder_stats=stats,
                        reason=REASON_TEMPLATE_MISSING,
                    ),
                    snapshot=snapshot,
                    schedule=schedule,
                    audit=True,
                )
                continue
        if not reminder_type:
            reminder_type = REMINDER_PAYMENT_PENDING
        logger.info(
            "payment_reminder.create.insert.start",
            extra={
                "account": _mask(snapshot.cuenta),
                "session_id": session_resolution.session_id,
                "status": STATUS_SCHEDULED,
                "scheduled_for": _scheduled_datetime(schedule.due_date).isoformat(),
                "reminder_type": reminder_type,
            },
        )
        reminder, status = upsert_scheduled_reminder(
            db,
            snapshot=snapshot,
            schedule=schedule,
            reminder_type=reminder_type,
            template_name=template_name,
            session_id=session_resolution.session_id,
            dry_run=dry_run,
        )
        if reminder is not None and stats.last_sent_at:
            next_allowed = _next_allowed_send_at(stats.last_sent_at)
            if next_allowed and reminder.scheduled_for and reminder.scheduled_for < next_allowed:
                reminder.scheduled_for = next_allowed
        result = _build_process_result(
            snapshot=snapshot,
            schedule=schedule,
            classification=status if status in {CLASS_ALREADY_SCHEDULED, CLASS_ALREADY_SENT, CLASS_ALREADY_TERMINAL} else classification,
            template_name=template_name,
            reminder_type=reminder_type,
            dry_run=dry_run,
            session_resolution=session_resolution,
            reminder_stats=stats,
            reason=status,
        )
        if reminder is not None:
            result["payment_reminder_id"] = getattr(reminder, "id", None)
        add_result(result)

    if not dry_run:
        try:
            db.commit()
            logger.info(
                "payment_reminder.create.commit.ok",
                extra={
                    "company_id": company_id,
                    "source": "sync",
                    "synced": len(results),
                },
            )
        except Exception as exc:
            db.rollback()
            logger.exception(
                "payment_reminder.create.failed",
                extra={
                    "company_id": company_id,
                    "source": "sync",
                    "error_type": exc.__class__.__name__,
                },
            )
            raise
    counts = _reason_counts(results)
    logger.info(
        "payment_reminder_candidate_sync_finished",
        extra={
            "company_id": company_id,
            "dry_run": dry_run,
            "chat_sessions_scanned": len(sessions),
            "chat_sessions_with_context": sessions_with_context,
            "synced": len(results),
            "reason_counts": counts,
        },
    )
    return {
        "synced": len(results),
        "chat_sessions_scanned": len(sessions),
        "chat_sessions_with_context": sessions_with_context,
        "reason_counts": counts,
        "results": results,
    }
