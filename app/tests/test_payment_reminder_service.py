import asyncio
from datetime import date, datetime, timedelta
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


@pytest.fixture(autouse=True)
def payment_reminder_test_defaults(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_REMINDERS_TEST_MODE", False)


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


def test_missing_bridge_payment_date_is_required_without_explicit_fallback(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_REMINDER_DEFAULT_WEEKDAY", None)
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "A4260506",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )

    assert "fecha_base_o_fecha_venta" in snapshot.missing_fields


def test_explicit_default_weekday_allows_missing_bridge_payment_date(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_REMINDER_DEFAULT_WEEKDAY", "FRIDAY")
    snapshot = payment_service._snapshot_from_item(
        {
            "source": "siga_bridge",
            "no_cuenta": "A4260506",
            "phone": "5214420001679",
            "customer_name": "Cliente Prueba",
            "balance": "100.00",
            "financial_summary": {"minimum_payment": "50.00"},
        },
        company_id=1,
    )

    assert "fecha_base_o_fecha_venta" not in snapshot.missing_fields


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
        folio="990001",
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

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []
        self.committed = False

    def query(self, model=None, *_args, **_kwargs):
        if any(hasattr(row, "__model__") for row in self.rows):
            return FakeQuery([row for row in self.rows if getattr(row, "__model__", model) is model])
        return FakeQuery(self.rows)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def chat_session(**overrides):
    values = {
        "id": 1,
        "phone": "5214420001679",
        "folio": "990001",
        "state": "ESPERA",
        "previous_state": None,
        "extra_json": {},
        "last_message": None,
        "last_message_at": None,
        "last_message_id": None,
        "updated_at": None,
        "unread_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakePaymentReminderBridge:
    def __init__(self):
        self.collection_calls = []

    async def get_collections(self, company_id, **kwargs):
        self.collection_calls.append(kwargs)
        cuenta = kwargs.get("cuenta") or "A900001"
        folio = kwargs.get("folio") or "990001"
        return {
            "items": [
                {
                    "no_cuenta": cuenta,
                    "folio": folio,
                    "phone": "5214420001679",
                    "customer_name": "Cliente Prueba",
                    "sale_date": "2026-05-19",
                    "balance": "100.00",
                    "minimum_payment": "50.00",
                    "account_status": "ACTIVA",
                    "process": "ACTIVO",
                }
            ]
        }

    async def get_account(self, cuenta, company_id, **kwargs):
        return {
            "account": cuenta,
            "sale_date": "2026-05-19",
            "status": "ACTIVA",
            "plan": {"minimum_payment": "50.00"},
        }

    async def get_payments(self, cuenta, company_id, **kwargs):
        return {"items": []}


class FakeMappedPaymentReminderBridge:
    def __init__(self, records, *, omit_phone=False):
        self.records = list(records)
        self.omit_phone = omit_phone
        self.collection_calls = []

    async def get_collections(self, company_id, **kwargs):
        self.collection_calls.append(kwargs)
        cuenta = kwargs.get("cuenta")
        folio = kwargs.get("folio")
        record = next(
            (
                item
                for item in self.records
                if (not cuenta or item.get("no_cuenta") == cuenta)
                and (not folio or item.get("folio") == folio)
            ),
            None,
        )
        if record is None:
            record = {
                "no_cuenta": cuenta or "A900001",
                "folio": folio or "990001",
                "phone": "5214271227177",
                "customer_name": "Cliente Prueba",
            }
        item = {
            "sale_date": "2026-05-19",
            "balance": "100.00",
            "minimum_payment": "50.00",
            "account_status": "ACTIVA",
            "process": "ACTIVO",
            **record,
        }
        if self.omit_phone:
            item.pop("phone", None)
        return {"items": [item]}

    async def get_account(self, cuenta, company_id, **kwargs):
        record = next((item for item in self.records if item.get("no_cuenta") == cuenta), {})
        phone = None if self.omit_phone else record.get("phone")
        return {
            "account": {
                "account": cuenta,
                "sale_date": "2026-05-19",
                "status": "ACTIVA",
                "process": "Cobranza",
                "plan": {"minimum_payment": "50.00"},
                "amounts": {"stored_balance": "100.00"},
            },
            "customer": {
                "name": record.get("customer_name") or "Cliente Prueba",
                "phones": [phone] if phone else [],
            },
        }

    async def get_payments(self, cuenta, company_id, **kwargs):
        return {"items": []}


REAL_ACCOUNT_1260522 = {
    "account": {
        "id_cuenta": 5991,
        "company_id": 1,
        "branch_id": 0,
        "account": "1260522",
        "customer_code": "PEALMAVA-2",
        "product": "CPU INTEL COREI3+ / AMD A4+, SSD 120GB, HDD 500GB, RAM 6GB",
        "sale_date": "2026-05-27 14:28:01",
        "warranty": "52",
        "initial_payment": 230,
        "down_payment": 229,
        "plan": {
            "term": 0,
            "minimum_payment": 215,
            "account_type": 2,
        },
        "amounts": {
            "cash_price": 8499,
            "stored_balance": 16769,
            "liquidation": 8269,
            "overdue": -1,
            "late_fee": -0.06,
        },
        "status": "Sano",
        "status_number": 1,
        "process": "Cobranza",
        "last_payment_date": "2026-05-22",
        "advisor": "DULCE M. MORENO",
        "collector": "MARIA F. OLVERA",
        "notes": "",
    },
    "customer": {
        "id_cliente": 9321,
        "customer_code": "PEALMAVA-2",
        "company_id": 1,
        "branch_id": None,
        "type": "PERSONA FISICA",
        "name": "MARTHA VALERIA PEREZ ALVARADO",
        "first_name": "MARTHA VALERIA",
        "last_name": "PEREZ ALVARADO",
        "email": "",
        "phones": ["7122145781"],
    },
    "payment_summary": {
        "initial_payment": 230,
        "payments_sum": 0,
        "paid_total": 230,
        "stored_balance": 16769,
        "liquidation": 8269,
        "overdue": -1,
    },
}


class FakeRealAccountBridge:
    def __init__(self, payload=None):
        self.payload = payload or REAL_ACCOUNT_1260522
        self.collection_calls = []
        self.account_calls = []

    async def get_collections(self, company_id, **kwargs):
        self.collection_calls.append(kwargs)
        account = kwargs.get("cuenta") or self.payload.get("account", {}).get("account") or "1260522"
        phones = self.payload.get("customer", {}).get("phones") or []
        return {
            "ok": True,
            "data": {
                "items": [
                    {
                        "no_cuenta": account,
                        "folio": kwargs.get("folio") or "1260522-F",
                        "phone": phones[0] if phones else None,
                    }
                ]
            },
            "error": None,
            "meta": {},
        }

    async def get_account(self, cuenta, company_id, **kwargs):
        self.account_calls.append({"cuenta": cuenta, "company_id": company_id, **kwargs})
        return {"ok": True, "data": self.payload, "error": None, "meta": {}}

    async def get_payments(self, cuenta, company_id, **kwargs):
        return {"ok": True, "data": {"items": []}, "error": None, "meta": {}}


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


def test_sync_uses_chat_sessions_as_candidate_source(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=10,
                phone="5214420001679",
                folio="990001",
                extra_json={"siga_bridge": {"verification_cache": {"snapshot": {"no_cuenta": "A900001"}}}},
            )
        ]
    )
    bridge = FakePaymentReminderBridge()

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=bridge,
            today=date(2026, 5, 26),
        )
    )

    assert result["synced"] == 1
    assert db.added
    reminder = db.added[0]
    assert reminder.session_id == 10
    assert reminder.cuenta == "A900001"
    assert reminder.due_date == date(2026, 5, 26)
    assert bridge.collection_calls[0]["folio"] == "990001"
    assert bridge.collection_calls[0]["cuenta"] == "A900001"


def test_sync_single_real_account_payload_schedules_reminder(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=42,
                phone="5217122145781",
                folio="1260522-F",
                extra_json={"verifications": [{"folio": "1260522-F", "no_cuenta": "1260522"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            cuenta="1260522",
            client=FakeRealAccountBridge(),
            today=date(2026, 5, 28),
        )
    )

    assert result["source"] == "single_account"
    assert result["synced"] == 1
    assert db.committed is True
    assert db.added
    reminder = db.added[0]
    assert reminder.session_id == 42
    assert reminder.cuenta == "1260522"
    assert reminder.phone == "5217122145781"
    assert reminder.status == STATUS_SCHEDULED
    assert reminder.due_date == date(2026, 6, 3)
    assert reminder.saldo_snapshot == Decimal("16769")
    assert reminder.monto_minimo_snapshot == Decimal("215")


def test_sync_single_real_account_without_phone_persists_skip_audit(monkeypatch):
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    payload = {
        **REAL_ACCOUNT_1260522,
        "customer": {
            **REAL_ACCOUNT_1260522["customer"],
            "phones": [],
        },
    }
    db = FakeDb([])

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            cuenta="1260522",
            client=FakeRealAccountBridge(payload),
            today=date(2026, 5, 28),
        )
    )

    assert result["source"] == "single_account"
    assert result["reason_counts"] == {payment_service.REASON_MISSING_BRIDGE_FIELDS: 1}
    assert result["results"][0]["reason"] == payment_service.REASON_MISSING_BRIDGE_FIELDS
    assert result["results"][0]["audited"] is True
    assert db.added
    audit = db.added[0]
    assert audit.status == payment_service.STATUS_SKIPPED
    assert audit.phone == "unknown"
    assert audit.error_code == payment_service.REASON_MISSING_BRIDGE_FIELDS
    assert "phone" in audit.error_message_sanitized


def test_payment_reminders_test_mode_blocks_non_allowed_phone(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_REMINDERS_TEST_MODE", True)
    monkeypatch.setattr(settings, "TEST_PHONE_ONLY", '["5214271227177"]')
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=42,
                phone="5217122145781",
                folio="1260522-F",
                extra_json={"verifications": [{"folio": "1260522-F", "no_cuenta": "1260522"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            cuenta="1260522",
            client=FakeRealAccountBridge(),
            today=date(2026, 5, 28),
        )
    )

    assert result["reason_counts"] == {payment_service.REASON_TEST_PHONE_NOT_ALLOWED: 1}
    assert result["results"][0]["test_mode"] is True
    assert result["results"][0]["test_phone_allowed"] is False
    assert result["results"][0]["reason"] == payment_service.REASON_TEST_PHONE_NOT_ALLOWED
    assert db.added
    audit = db.added[0]
    assert audit.status == payment_service.STATUS_SKIPPED
    assert audit.error_code == payment_service.REASON_TEST_PHONE_NOT_ALLOWED


def test_weekly_frequency_blocks_until_seven_full_days():
    last_sent_at = datetime(2026, 5, 28, 10, 30, 0)
    sent_reminder = SimpleNamespace(
        id=77,
        status=payment_service.STATUS_SENT,
        cuenta="1260522",
        session_id=42,
        sent_at=last_sent_at,
    )

    blocked, last_sent, next_allowed = payment_service._weekly_frequency_blocked(
        FakeDb([sent_reminder]),
        cuenta="1260522",
        session_id=42,
        now=last_sent_at + timedelta(days=6, hours=23),
    )

    assert blocked is True
    assert last_sent is sent_reminder
    assert next_allowed == datetime(2026, 6, 4, 10, 30, 0)


def test_weekly_frequency_allows_after_seven_full_days():
    last_sent_at = datetime(2026, 5, 28, 10, 30, 0)
    sent_reminder = SimpleNamespace(
        id=77,
        status=payment_service.STATUS_SENT,
        cuenta="1260522",
        session_id=42,
        sent_at=last_sent_at,
    )

    blocked, _last_sent, next_allowed = payment_service._weekly_frequency_blocked(
        FakeDb([sent_reminder]),
        cuenta="1260522",
        session_id=42,
        now=last_sent_at + timedelta(days=7, seconds=1),
    )

    assert blocked is False
    assert next_allowed == datetime(2026, 6, 4, 10, 30, 0)


def test_weekly_frequency_uses_visible_payment_reminder_message_history():
    message_created_at = datetime(2026, 5, 28, 10, 30, 0)
    message = SimpleNamespace(
        __model__=payment_service.Message,
        id=500,
        session_id=42,
        direction="out",
        type="payment_reminder",
        created_at=message_created_at,
    )

    blocked, last_sent, next_allowed = payment_service._weekly_frequency_blocked(
        FakeDb([message]),
        cuenta="1260522",
        session_id=42,
        now=message_created_at + timedelta(minutes=1),
    )

    assert blocked is True
    assert last_sent is message
    assert next_allowed == datetime(2026, 6, 4, 10, 30, 0)


def test_next_reminder_after_send_uses_sent_at_plus_seven_days():
    previous_schedule = PaymentSchedule(
        due_date=date(2026, 5, 27),
        next_due_date=date(2026, 6, 3),
        weekday=2,
        source="bridge_fecha_venta_plus_7",
    )
    sent_at = datetime(2026, 5, 28, 20, 40, 31)

    next_schedule, scheduled_for = payment_service._next_reminder_schedule_after_send(
        sent_at=sent_at,
        previous_schedule=previous_schedule,
    )

    assert next_schedule.due_date == date(2026, 6, 4)
    assert next_schedule.next_due_date == date(2026, 6, 11)
    assert next_schedule.source == "last_reminder_sent_at_plus_7"
    assert scheduled_for == datetime(2026, 6, 4, 20, 40, 31)


def test_upsert_does_not_reactivate_failed_reminder_every_sync(monkeypatch):
    failed = SimpleNamespace(
        id=123,
        status=payment_service.STATUS_FAILED,
        phone="5214420001679",
        folio=None,
        cuenta="CTA-1",
        due_date=date(2026, 6, 9),
        next_due_date=None,
        scheduled_for=datetime(2026, 6, 9, 10, 0, 0),
        template_name="payment_pending",
        receipt_status=None,
        receipt_id=None,
        saldo_snapshot=None,
        monto_minimo_snapshot=None,
        bridge_found=False,
        bridge_snapshot_hash=None,
        updated_at=None,
    )
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: failed)
    snapshot = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="CTA-1",
        folio="990001",
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
        SimpleNamespace(add=lambda reminder: pytest.fail("should not create duplicate")),
        snapshot=snapshot,
        schedule=schedule,
        reminder_type=REMINDER_PAYMENT_PENDING,
        template_name="payment_pending",
        session_id=42,
        dry_run=False,
    )

    assert reminder is failed
    assert status == payment_service.CLASS_ALREADY_TERMINAL
    assert failed.status == payment_service.STATUS_FAILED
    assert failed.scheduled_for == datetime(2026, 6, 9, 10, 0, 0)


def test_sync_weekly_frequency_block_schedules_future_reminder(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    next_allowed = datetime(2026, 6, 4, 20, 40, 31)
    monkeypatch.setattr(
        payment_service,
        "_weekly_frequency_blocked",
        lambda *args, **kwargs: (True, SimpleNamespace(sent_at=datetime(2026, 5, 28, 20, 40, 31)), next_allowed),
    )
    monkeypatch.setattr(payment_service, "_reminder_stats", lambda *args, **kwargs: payment_service.ReminderStats())
    db = FakeDb(
        [
            chat_session(
                id=42,
                phone="5217122145781",
                folio="1260522-F",
                extra_json={"verifications": [{"folio": "1260522-F", "no_cuenta": "1260522"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            cuenta="1260522",
            client=FakeRealAccountBridge(),
            today=date(2026, 6, 3),
        )
    )

    assert result["results"][0]["reason"] == payment_service.REASON_WEEKLY_FREQUENCY_BLOCKED
    assert db.added
    reminder = db.added[0]
    assert reminder.status == payment_service.STATUS_SCHEDULED
    assert reminder.due_date == date(2026, 6, 4)
    assert reminder.next_due_date == date(2026, 6, 11)
    assert reminder.scheduled_for == next_allowed
    assert reminder.error_code == payment_service.REASON_WEEKLY_FREQUENCY_BLOCKED


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


def test_reminder_matches_raw_session_account_to_prefixed_bridge_account():
    session = chat_session(
        id=1,
        folio="990001",
        extra_json={"siga_bridge": {"verification_cache": {"snapshot": {"no_cuenta": "900001"}}}},
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

    assert resolution.found is True
    assert resolution.session_id == 1


def test_reminder_requires_folio_account_pair_when_session_has_multiple_verifications():
    session = chat_session(
        id=90050,
        phone="5214271227177",
        folio="16774",
        extra_json={
            "verifications": [
                {"folio": "990001", "no_cuenta": "A900001"},
                {"folio": "16774", "no_cuenta": "A900002"},
            ]
        },
    )

    mixed = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214271227177",
        folio="16774",
        account_reference_formatted="A900001",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session]),
        snapshot=mixed,
        session_id=90050,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_CHAT_SESSION_ACCOUNT_MISMATCH

    correct = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900002",
        phone="5214271227177",
        folio="16774",
        account_reference_formatted="A900002",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session]),
        snapshot=correct,
        session_id=90050,
    )

    assert resolution.found is True
    assert resolution.session_id == 90050


def test_same_account_with_two_folios_requires_folio_to_avoid_ambiguity():
    session = chat_session(
        id=90050,
        phone="5214271227177",
        folio="16774",
        extra_json={
            "verifications": [
                {"folio": "990001", "no_cuenta": "A900001"},
                {"folio": "16774", "no_cuenta": "A900001"},
            ]
        },
    )

    account_only = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214271227177",
        account_reference_formatted="A900001",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session]),
        snapshot=account_only,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_AMBIGUOUS_CHAT_SESSION

    with_folio = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900001",
        phone="5214271227177",
        folio="990001",
        account_reference_formatted="A900001",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session]),
        snapshot=with_folio,
    )

    assert resolution.found is True
    assert resolution.session_id == 90050


def test_phone_with_multiple_sessions_resolves_a900003_only_with_matching_folio():
    session_990003 = chat_session(
        id=90052,
        phone="5214271644542",
        folio="990003",
        extra_json={"verifications": [{"folio": "990003", "no_cuenta": "A900003"}]},
    )
    session_16511 = chat_session(
        id=90054,
        phone="5214271644542",
        folio="16511",
        extra_json={"verifications": [{"folio": "16511", "no_cuenta": "A900003"}]},
    )

    account_only = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900003",
        phone="5214271644542",
        account_reference_formatted="A900003",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session_990003, session_16511]),
        snapshot=account_only,
    )

    assert resolution.found is False
    assert resolution.reason == payment_service.CLASS_AMBIGUOUS_CHAT_SESSION

    with_folio = BridgeAccountSnapshot(
        bridge_found=True,
        company_id=1,
        cuenta="A900003",
        phone="5214271644542",
        folio="990003",
        account_reference_formatted="A900003",
    )
    resolution = payment_service.resolve_chat_session_for_reminder(
        FakeDb([session_990003, session_16511]),
        snapshot=with_folio,
    )

    assert resolution.found is True
    assert resolution.session_id == 90052


def test_sync_expands_multiple_verification_pairs_without_mixing_folios(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90050,
                phone="5214271227177",
                folio="16774",
                extra_json={
                    "verifications": [
                        {"folio": "990001", "no_cuenta": "A900001"},
                        {"folio": "16774", "no_cuenta": "A900002"},
                    ]
                },
            )
        ]
    )
    bridge = FakeMappedPaymentReminderBridge(
        [
            {"folio": "990001", "no_cuenta": "A900001", "phone": "5214271227177"},
            {"folio": "16774", "no_cuenta": "A900002", "phone": "5214271227177"},
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=bridge,
            today=date(2026, 5, 26),
        )
    )

    assert result["synced"] == 2
    assert {(call["folio"], call["cuenta"]) for call in bridge.collection_calls} == {
        ("990001", "A900001"),
        ("16774", "A900002"),
    }
    assert {(reminder.folio, reminder.cuenta) for reminder in db.added} == {
        ("990001", "A900001"),
        ("16774", "A900002"),
    }


def test_zero_folio_is_skipped_with_clear_error(monkeypatch):
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90043,
                phone="5214271665615",
                folio="00000",
                extra_json={"no_cuenta": "B900002"},
            )
        ]
    )
    bridge = FakeMappedPaymentReminderBridge([])

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=bridge,
            today=date(2026, 5, 26),
        )
    )

    assert bridge.collection_calls == []
    assert result["reason_counts"] == {payment_service.REASON_INVALID_FOLIO: 1}
    assert db.added
    audit = db.added[0]
    assert audit.status == payment_service.STATUS_SKIPPED
    assert audit.error_code == payment_service.REASON_INVALID_FOLIO
    assert "folio" in audit.error_message_sanitized


def test_test_phone_only_allows_configured_payment_reminder_phone(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_REMINDERS_TEST_MODE", True)
    monkeypatch.setattr(settings, "TEST_PHONE_ONLY", '["5214271227177"]')
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90050,
                phone="5214271227177",
                folio="990001",
                extra_json={"verifications": [{"folio": "990001", "no_cuenta": "A900001"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=FakeMappedPaymentReminderBridge(
                [{"folio": "990001", "no_cuenta": "A900001", "phone": "5214271227177"}]
            ),
            today=date(2026, 5, 26),
        )
    )

    assert result["results"][0]["test_mode"] is True
    assert result["results"][0]["test_phone_allowed"] is True
    assert result["results"][0]["reason"] == payment_service.STATUS_SCHEDULED
    assert db.added[0].phone == "5214271227177"


def test_local_session_phone_is_used_when_bridge_omits_phone(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90052,
                phone="5214271644542",
                folio="990003",
                extra_json={"verifications": [{"folio": "990003", "no_cuenta": "A900003"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=FakeMappedPaymentReminderBridge(
                [{"folio": "990003", "no_cuenta": "A900003"}],
                omit_phone=True,
            ),
            today=date(2026, 5, 26),
        )
    )

    assert result["reason_counts"] == {}
    assert db.added
    reminder = db.added[0]
    assert reminder.phone == "5214271644542"
    assert reminder.folio == "990003"
    assert reminder.cuenta == "A900003"


def test_sync_prefers_chat_session_phone_over_bridge_phone_for_matching_folio_account(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90050,
                phone="5214271227177",
                folio="990001",
                extra_json={"verifications": [{"folio": "990001", "no_cuenta": "A900001"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            client=FakeMappedPaymentReminderBridge(
                [{"folio": "990001", "no_cuenta": "A900001", "phone": "5214411197467"}]
            ),
            today=date(2026, 5, 26),
        )
    )

    assert result["synced"] == 1
    assert db.added
    reminder = db.added[0]
    assert reminder.session_id == 90050
    assert reminder.phone == "5214271227177"
    assert reminder.folio == "990001"
    assert reminder.cuenta == "A900001"


def test_single_account_sync_resolves_phone_from_session_that_entered_folio(monkeypatch):
    monkeypatch.setattr(settings, "META_PAYMENT_PENDING_TEMPLATE_NAME", "mxcomp_pago_pendiente_v1")
    monkeypatch.setattr(payment_service, "_existing_reminder", lambda *args, **kwargs: None)
    db = FakeDb(
        [
            chat_session(
                id=90052,
                phone="5214271644542",
                folio="990003",
                extra_json={"verifications": [{"folio": "990003", "no_cuenta": "A900003"}]},
            )
        ]
    )

    result = asyncio.run(
        payment_service.sync_payment_reminder_candidates(
            db,
            company_id=1,
            limit=5,
            dry_run=False,
            cuenta="A900003",
            folio="990003",
            client=FakeMappedPaymentReminderBridge(
                [{"folio": "990003", "no_cuenta": "A900003", "phone": "5214411197467"}]
            ),
            today=date(2026, 5, 26),
        )
    )

    assert result["source"] == "single_account"
    assert result["synced"] == 1
    assert db.added
    reminder = db.added[0]
    assert reminder.session_id == 90052
    assert reminder.phone == "5214271644542"
    assert reminder.folio == "990003"
    assert reminder.cuenta == "A900003"


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


def test_mark_chat_session_cobranza_uses_state_not_status():
    db = FakeDb([])
    session = chat_session(id=8, state="ESPERA")

    payment_service._mark_chat_session_cobranza(db, session)

    assert session.state == "COBRANZA"
    assert session.previous_state == "ESPERA"
    assert session.updated_at is not None
    assert session in db.added
