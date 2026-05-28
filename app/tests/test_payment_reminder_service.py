import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.content.message_builder import MessageBuilder
from app.config.settings import settings
import app.services.payment_reminder_service as payment_service
from app.services.collections_panel_service import resolve_collection_payment_state
from app.services.payment_reminder_service import (
    BridgeAccountSnapshot,
    CLASS_ALREADY_SCHEDULED,
    CLASS_DUE_TODAY_UNPAID,
    CLASS_OVERDUE_UNPAID,
    CLASS_SETTLED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_UNPAID,
    PaymentSchedule,
    PaymentScheduleError,
    REMINDER_PAYMENT_PENDING,
    STATUS_SCHEDULED,
    calculate_due_schedule,
    classify_reminder_case,
    normalize_phone_for_whatsapp,
    upsert_scheduled_reminder,
)


def test_normalizes_local_mexico_phone():
    assert normalize_phone_for_whatsapp("4420001679") == "5214420001679"
    assert normalize_phone_for_whatsapp("524421234567") == "5214421234567"
    assert normalize_phone_for_whatsapp("5214421234567") == "5214421234567"


def test_bridge_next_payment_date_has_priority_over_default_weekday():
    schedule = calculate_due_schedule(
        sale_date=date(2026, 5, 1),
        today=date(2026, 5, 25),
        bridge_next_payment_date=date(2026, 5, 28),
        bridge_weekday=1,
        default_weekday="TUESDAY",
    )

    assert schedule.due_date == date(2026, 5, 28)
    assert schedule.source == "bridge_next_payment_date"


def test_sale_date_tuesday_keeps_customer_weekly_tuesday_cycle():
    schedule = calculate_due_schedule(
        sale_date=date(2026, 5, 19),
        today=date(2026, 6, 10),
    )

    assert schedule.due_date == date(2026, 6, 9)
    assert schedule.next_due_date == date(2026, 6, 16)
    assert schedule.weekday == 1
    assert schedule.source == "bridge_fecha_venta_plus_7"
    assert schedule.base_date == date(2026, 5, 19)
    assert schedule.fallback_used is False


def test_sale_date_friday_keeps_customer_weekly_friday_cycle():
    schedule = calculate_due_schedule(
        sale_date=date(2026, 5, 22),
        today=date(2026, 6, 10),
        default_weekday="TUESDAY",
    )

    assert schedule.due_date == date(2026, 6, 5)
    assert schedule.next_due_date == date(2026, 6, 12)
    assert schedule.weekday == 4
    assert schedule.source == "bridge_fecha_venta_plus_7"


def test_bridge_payment_base_date_is_used_without_global_weekday_override():
    schedule = calculate_due_schedule(
        payment_base_date=date(2026, 5, 22),
        today=date(2026, 6, 10),
        default_weekday="TUESDAY",
        allow_default_weekday_fallback=True,
    )

    assert schedule.due_date == date(2026, 6, 5)
    assert schedule.next_due_date == date(2026, 6, 12)
    assert schedule.weekday == 4
    assert schedule.source == "bridge_payment_base_date"
    assert schedule.base_date_source == "bridge_payment_base_date"


def test_default_weekday_does_not_override_valid_bridge_sale_date():
    schedule = calculate_due_schedule(
        sale_date=date(2026, 5, 19),
        today=date(2026, 5, 26),
        default_weekday="FRIDAY",
        allow_default_weekday_fallback=True,
    )

    assert schedule.due_date == date(2026, 5, 26)
    assert schedule.weekday == 1
    assert schedule.source == "bridge_fecha_venta_plus_7"
    assert schedule.fallback_used is False


def test_default_weekday_only_used_when_fallback_is_explicit():
    with pytest.raises(PaymentScheduleError, match="missing_bridge_payment_base_date"):
        calculate_due_schedule(
            sale_date=None,
            today=date(2026, 6, 10),
            default_weekday="FRIDAY",
            allow_default_weekday_fallback=False,
        )

    schedule = calculate_due_schedule(
        sale_date=None,
        today=date(2026, 6, 10),
        default_weekday="FRIDAY",
        allow_default_weekday_fallback=True,
    )

    assert schedule.due_date == date(2026, 6, 12)
    assert schedule.next_due_date == date(2026, 6, 19)
    assert schedule.source == "env_default_weekday_fallback"
    assert schedule.fallback_used is True
    assert schedule.fallback_reason == "missing_bridge_payment_base_date"


def test_missing_bridge_date_without_fallback_does_not_schedule():
    with pytest.raises(PaymentScheduleError):
        calculate_due_schedule(sale_date=None, today=date(2026, 5, 25))


def test_collection_payment_state_paid_from_balance_zero():
    state = resolve_collection_payment_state(
        {
            "source": "siga_bridge",
            "balance": "0.00",
            "is_paid": False,
        }
    )

    assert state["estado_pago"] == PAYMENT_STATUS_PAID
    assert state["fuente_estado_pago"] == "bridge"


def test_collection_payment_state_paid_from_status_text():
    state = resolve_collection_payment_state(
        {
            "source": "siga_bridge",
            "balance": "100.00",
            "account_status": "Liquidado",
        }
    )

    assert state["estado_pago"] == PAYMENT_STATUS_PAID


def test_collection_payment_state_unpaid_with_pending_balance():
    state = resolve_collection_payment_state(
        {
            "source": "siga_bridge",
            "balance": "100.00",
            "account_status": "Activo",
        }
    )

    assert state["estado_pago"] == PAYMENT_STATUS_UNPAID


def test_unpaid_due_today_can_send_pending_template():
    classification = classify_reminder_case(
        bridge_found=True,
        missing_fields=[],
        payment_status=PAYMENT_STATUS_UNPAID,
        due_date=date(2026, 5, 25),
        today=date(2026, 5, 25),
    )

    assert classification == CLASS_DUE_TODAY_UNPAID


def test_unpaid_overdue_can_send_overdue_template():
    classification = classify_reminder_case(
        bridge_found=True,
        missing_fields=[],
        payment_status=PAYMENT_STATUS_UNPAID,
        due_date=date(2026, 5, 24),
        today=date(2026, 5, 25),
    )

    assert classification == CLASS_OVERDUE_UNPAID


def test_paid_never_classifies_for_send():
    classification = classify_reminder_case(
        bridge_found=True,
        missing_fields=[],
        payment_status=PAYMENT_STATUS_PAID,
        due_date=date(2026, 5, 25),
        today=date(2026, 5, 25),
    )

    assert classification == CLASS_SETTLED


def test_uploaded_receipt_marker_does_not_mark_account_paid():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "CTA-1",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
            "receipt_status": "uploaded",
        },
        company_id=1,
    )

    assert snapshot.payment_status == PAYMENT_STATUS_UNPAID
    assert snapshot.settled is False


def test_account_reference_with_prefix_a_is_preserved_in_template():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "A4260506",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 5, 26),
        next_due_date=date(2026, 6, 2),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    params = payment_service.build_template_parameters(
        reminder_type=REMINDER_PAYMENT_PENDING,
        snapshot=snapshot,
        schedule=schedule,
    )

    assert snapshot.account_reference_formatted == "A4260506"
    assert params[1] == "A4260506"


def test_account_reference_with_prefix_b_is_preserved_in_template():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "B4260506",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 5, 26),
        next_due_date=date(2026, 6, 2),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    params = payment_service.build_template_parameters(
        reminder_type=REMINDER_PAYMENT_PENDING,
        snapshot=snapshot,
        schedule=schedule,
    )

    assert snapshot.account_reference_formatted == "B4260506"
    assert params[1] == "B4260506"


def test_prefixed_bridge_account_wins_over_raw_numeric_account():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "4260506",
            "account": {"cuenta": "B4260506"},
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 5, 26),
        next_due_date=date(2026, 6, 2),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    params = payment_service.build_template_parameters(
        reminder_type=REMINDER_PAYMENT_PENDING,
        snapshot=snapshot,
        schedule=schedule,
    )

    assert snapshot.account_reference_raw == "4260506"
    assert snapshot.account_reference_formatted == "B4260506"
    assert params[1] == "B4260506"


def test_missing_required_account_prefix_blocks_reminder():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "4260506",
            "requires_account_prefix": True,
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )

    assert snapshot.account_reference_valid is False
    assert snapshot.account_reference_reason == "account_prefix_required_but_missing"
    assert "cuenta_formateada" in snapshot.missing_fields


def test_reminder_and_comprobante_access_share_account_reference_format():
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "B4260506",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )

    assert snapshot.account_reference_formatted == payment_service.format_account_reference("B4260506")
    assert payment_service.format_account_reference("4260506") == "A4260506"
    assert "*B4260506*" in MessageBuilder.info_comprobante_acceso("B4260506", "CLI-123")


def test_dry_run_payload_has_simple_payment_state_and_no_receipt_status():
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="CTA-1",
        phone="5214420001679",
        balance=Decimal("100.00"),
        minimum_payment=Decimal("50.00"),
        payment_status=PAYMENT_STATUS_UNPAID,
        payment_status_source="bridge",
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 6, 9),
        next_due_date=date(2026, 6, 16),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
        base_date=date(2026, 6, 2),
        base_date_source="bridge_fecha_venta",
    )

    result = payment_service._build_process_result(
        snapshot=snapshot,
        schedule=schedule,
        classification=CLASS_DUE_TODAY_UNPAID,
        template_name="payment_pending",
        reminder_type=REMINDER_PAYMENT_PENDING,
        dry_run=True,
        session_resolution=payment_service.ChatSessionResolution(
            SimpleNamespace(id=10),
            True,
            "single_phone_match",
            "phone",
            1,
        ),
    )

    assert result["estado_pago"] == PAYMENT_STATUS_UNPAID
    assert result["fuente_estado_pago"] == "bridge"
    assert result["cuenta_raw"] == "CTA-1"
    assert result["cuenta_formateada"] == "CTA-1"
    assert "fuente_formato_cuenta" in result
    assert "cuenta_formateada_valida" in result
    assert result["should_send"] is True
    assert result["chat_session_found"] is True
    assert result["would_create_conversation_message"] is True
    assert "receipt_status" not in result


def test_no_receipt_under_review_template_is_used(monkeypatch):
    monkeypatch.setattr(settings, "META_RECEIPT_UNDER_REVIEW_TEMPLATE_NAME", "receipt_review")

    template_name, reminder_type = payment_service._template_for_classification(CLASS_DUE_TODAY_UNPAID)

    assert template_name != "receipt_review"
    assert reminder_type == REMINDER_PAYMENT_PENDING


def test_existing_active_reminder_is_not_duplicated(monkeypatch):
    existing = SimpleNamespace(
        status=STATUS_SCHEDULED,
        phone="5214420001679",
        folio=None,
        cuenta="CTA-1",
        due_date=None,
        next_due_date=None,
        scheduled_for=None,
        template_name=None,
        receipt_status=None,
        receipt_id=None,
        saldo_snapshot=None,
        monto_minimo_snapshot=None,
        bridge_found=False,
        bridge_snapshot_hash=None,
        updated_at=None,
    )
    fake_db = SimpleNamespace(add=lambda reminder: pytest.fail("should not add duplicate reminder"))
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="CTA-1",
        phone="5214420001679",
        balance=Decimal("100.00"),
        minimum_payment=Decimal("50.00"),
        payment_status=PAYMENT_STATUS_UNPAID,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 6, 9),
        next_due_date=date(2026, 6, 16),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
        base_date=date(2026, 6, 2),
        base_date_source="bridge_fecha_venta",
    )
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: existing)

    reminder, status = upsert_scheduled_reminder(
        fake_db,
        snapshot=snapshot,
        schedule=schedule,
        reminder_type=REMINDER_PAYMENT_PENDING,
        template_name="payment_pending",
        session_id=10,
        dry_run=False,
    )

    assert reminder is existing
    assert status == CLASS_ALREADY_SCHEDULED


def test_upsert_does_not_schedule_without_session_id():
    fake_db = SimpleNamespace(add=lambda reminder: pytest.fail("should not add without chat session"))
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="CTA-1",
        phone="5214420001679",
        balance=Decimal("100.00"),
        minimum_payment=Decimal("50.00"),
        payment_status=PAYMENT_STATUS_UNPAID,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 6, 9),
        next_due_date=date(2026, 6, 16),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    reminder, status = upsert_scheduled_reminder(
        fake_db,
        snapshot=snapshot,
        schedule=schedule,
        reminder_type=REMINDER_PAYMENT_PENDING,
        template_name="payment_pending",
        dry_run=False,
    )

    assert reminder is None
    assert status == payment_service.CLASS_MISSING_CHAT_SESSION


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.rows)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


def chat_session(**overrides):
    values = {
        "id": 1,
        "phone": "5214420001679",
        "folio": "990001",
        "extra_json": {},
        "last_message": None,
        "last_message_at": None,
        "last_message_id": None,
        "unread_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_reminder_requires_existing_chat_session():
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214420001679",
        folio="990001",
    )

    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([]),
        snapshot=snapshot,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_MISSING_CHAT_SESSION


def test_reminder_resolves_session_by_folio_when_phone_has_multiple_sessions():
    session_a = chat_session(id=1, folio="OLD")
    session_b = chat_session(id=2, folio="990001")
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214420001679",
        folio="990001",
    )

    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session_a, session_b]),
        snapshot=snapshot,
    )

    assert resolution.found is True
    assert resolution.session_id == 2
    assert resolution.reason == "folio_match"


def test_reminder_does_not_resolve_ambiguous_chat_sessions():
    session_a = chat_session(id=1, folio=None)
    session_b = chat_session(id=2, folio=None)
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214420001679",
        folio="990001",
    )

    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session_a, session_b]),
        snapshot=snapshot,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_AMBIGUOUS_CHAT_SESSION


def test_reminder_detects_chat_session_account_mismatch():
    session = chat_session(
        id=1,
        folio="990001",
        extra_json={"siga_bridge": {"verification_cache": {"snapshot": {"no_cuenta": "B900001"}}}},
    )
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214420001679",
        folio="990001",
        account_reference_formatted="A900001",
    )

    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session]),
        snapshot=snapshot,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_CHAT_SESSION_ACCOUNT_MISMATCH


def test_dry_run_result_blocks_send_without_chat_session():
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214420001679",
        balance=Decimal("100.00"),
        minimum_payment=Decimal("50.00"),
        payment_status=PAYMENT_STATUS_UNPAID,
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 6, 9),
        next_due_date=date(2026, 6, 16),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    result = payment_service._build_process_result(
        snapshot=snapshot,
        schedule=schedule,
        classification=CLASS_DUE_TODAY_UNPAID,
        template_name="payment_pending",
        reminder_type=REMINDER_PAYMENT_PENDING,
        dry_run=True,
        session_resolution=payment_service.ChatSessionResolution(
            None,
            False,
            payment_service.CLASS_MISSING_CHAT_SESSION,
        ),
    )

    assert result["should_send"] is False
    assert result["chat_session_found"] is False
    assert result["chat_session_match_reason"] == payment_service.CLASS_MISSING_CHAT_SESSION
    assert result["would_create_conversation_message"] is False


def test_sent_reminder_is_saved_as_conversation_message(monkeypatch):
    events = []

    async def send_to_all(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr(payment_service, "manager", SimpleNamespace(send_to_all=send_to_all))

    db = FakeDb([])
    session = chat_session(id=7, phone="5214420001679")
    reminder = SimpleNamespace(id=99, phone="5214420001679", template_name="mxcomp_pago_vencido_v1")
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        folio="990001",
        phone="5214420001679",
        customer_name="Cliente Prueba",
        balance=Decimal("100.00"),
        minimum_payment=Decimal("50.00"),
        account_reference_formatted="A900001",
    )
    schedule = PaymentSchedule(
        due_date=date(2026, 6, 9),
        next_due_date=date(2026, 6, 16),
        weekday=1,
        source="bridge_fecha_venta_plus_7",
    )

    message = asyncio.run(
        payment_service._record_sent_conversation_message(
            db,
            session=session,
            reminder=reminder,
            snapshot=snapshot,
            schedule=schedule,
            reminder_type=REMINDER_PAYMENT_PENDING,
            meta_message_id="wamid.test.payment_reminder",
        )
    )

    assert message in db.added
    assert message.direction == "out"
    assert message.type == "payment_reminder"
    assert message.message_id == "wamid.test.payment_reminder"
    assert session.last_message.startswith("Recordatorio de pago enviado")
    assert session.last_message_at is not None
    assert any(event.get("type") == "new_message" for event in events)
