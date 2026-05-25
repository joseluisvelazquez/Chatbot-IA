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
    is_test_phone_allowed,
    normalize_phone_for_whatsapp,
    upsert_scheduled_reminder,
)


def test_normalizes_local_mexico_phone_and_applies_test_gate(monkeypatch):
    monkeypatch.setattr(settings, "TEST_PHONE_ONLY", ["5214420001679"])

    assert normalize_phone_for_whatsapp("4420001679") == "5214420001679"
    assert is_test_phone_allowed("4420001679") is True
    assert is_test_phone_allowed("4270000000") is False


def test_empty_test_phone_only_blocks_real_send(monkeypatch):
    monkeypatch.setattr(settings, "TEST_PHONE_ONLY", [])

    assert is_test_phone_allowed("5214420001679") is False


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
    )

    assert result["estado_pago"] == PAYMENT_STATUS_UNPAID
    assert result["fuente_estado_pago"] == "bridge"
    assert result["cuenta_raw"] == "CTA-1"
    assert result["cuenta_formateada"] == "CTA-1"
    assert "fuente_formato_cuenta" in result
    assert "cuenta_formateada_valida" in result
    assert result["should_send"] is True
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
        dry_run=False,
    )

    assert reminder is existing
    assert status == CLASS_ALREADY_SCHEDULED
