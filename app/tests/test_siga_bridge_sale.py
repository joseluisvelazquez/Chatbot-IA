import asyncio

from app.core.states.state_renderer import render_state
from app.core.states.states import ChatState
from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
from app.services.verification_tracker import track_verification
from app.services.siga_bridge_cache import (
    get_cached_verification,
    get_or_fetch_verification,
    upsert_cached_verification,
)
from app.services.siga_bridge_sale import (
    bridge_address_from_payload,
    bridge_sale_from_payload,
    bridge_verification_found,
    normalize_siga_verification_snapshot,
)
from app.utils.product_mapping import requires_components_check


class DummySession:
    id = 123
    folio = "16809"
    phone = "524421234567"
    state = "INICIO"
    previous_state = None
    extra_json = {}


def run(coro):
    return asyncio.run(coro)


def verification_payload(**overrides):
    payload = {
        "found": True,
        "source_table": "bitacora_ventas",
        "sale": {
            "folio": "16809",
            "no_cuenta": "60436",
            "nombre_completo": "CLIENTE DEMO",
            "sku_bitacora_v": "PC-MAXICA",
            "fecha_venta": "2026-05-05",
            "pago": "699.00",
        },
        "customer": {
            "nombre": "CLIENTE DEMO",
            "address": {
                "city": "Cadereyta de Montes",
                "colonia": "Sombrerete",
                "codigo_postal": "76536",
                "full": None,
            },
        },
        "account": {"no_cuenta": "60436", "saldo": "1200.50"},
        "payment_summary": {
            "saldo": "1200.50",
            "plan": "Semanal",
            "pago_minimo": "215",
        },
        "recent_payments": [{"importe": "215"}],
        "components": [{"name": "CPU"}],
    }
    payload.update(overrides)
    return payload


LONG_PC_DESCRIPTION = (
    "CPU INTEL COREI3+ / AMD A4+, SSD 120GB, HDD 500GB, RAM 6GB, "
    "MONITOR PANORAMICO/CUADRADO 19+, TECLADO MULTIMEDIA, MOUSE OPTICO, "
    "BOCINAS 2.0 Y ADAPTADOR WIFI"
)


def test_bridge_verification_payload_builds_sale_fallback():
    payload = verification_payload()

    venta = bridge_sale_from_payload(payload)

    assert bridge_verification_found(payload) is True
    assert venta.folio == "16809"
    assert venta.no_cuenta == "60436"
    assert venta.nombre_completo == "CLIENTE DEMO"
    assert str(venta.pago) == "699.00"


def test_pc_maxica_sku_wins_over_long_description():
    payload = verification_payload(
        sale={
            "folio": "16809",
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "descripcion": LONG_PC_DESCRIPTION,
            "fecha_venta": "2026-05-05",
        }
    )

    snapshot = normalize_siga_verification_snapshot(payload)
    venta = bridge_sale_from_payload(payload)

    assert snapshot["sale"]["product"] == "PC-MAXICA"
    assert snapshot["sale"]["product_description"] == LONG_PC_DESCRIPTION
    assert venta.sku_bitacora_v == "PC-MAXICA"
    assert venta.descripcion == LONG_PC_DESCRIPTION
    assert requires_components_check(venta) is True


def test_renderer_uses_pc_maxica_commercial_name():
    session = DummySession()
    session.extra_json = {}
    payload = verification_payload(
        sale={
            "folio": "16809",
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "descripcion": LONG_PC_DESCRIPTION,
        }
    )
    upsert_cached_verification(session, "16809", payload, raw=payload)

    reply, _buttons, _image_id = render_state(ChatState.CONFIRMAR_PRODUCTO, session, db=None)

    assert "PC-MAXICA" in reply
    assert LONG_PC_DESCRIPTION not in reply


def test_normalizer_accepts_v1_wrapper_and_builds_snapshot():
    payload = {
        "ok": True,
        "data": verification_payload(),
        "error": None,
        "meta": {
            "version": "v1",
            "timestamp": "2026-05-05T12:00:00-06:00",
            "action": "verification",
        },
    }

    snapshot = normalize_siga_verification_snapshot(payload)

    assert snapshot["found"] is True
    assert snapshot["folio"] == "16809"
    assert snapshot["no_cuenta"] == "60436"
    assert snapshot["customer"]["name"] == "CLIENTE DEMO"
    assert snapshot["source"]["table"] == "bitacora_ventas"


def test_normalizer_preserves_fecha_venta_in_snapshot():
    snapshot = normalize_siga_verification_snapshot(
        verification_payload(sale={"folio": "16809", "fecha_venta": "2026-04-30"})
    )

    assert snapshot["fecha_venta"] == "2026-04-30"
    assert snapshot["sale"]["fecha_venta"] == "2026-04-30"
    assert snapshot["sale"]["sale_date"] == "2026-04-30"


def test_normalizer_flat_found_false_is_safe_snapshot():
    snapshot = normalize_siga_verification_snapshot({"found": False, "folio": "999"})

    assert snapshot["found"] is False
    assert snapshot["folio"] == "999"
    assert snapshot["no_cuenta"] is None
    assert snapshot["payment"]["available"] is False


def test_normalizer_payment_object_does_not_leak_raw_object():
    snapshot = normalize_siga_verification_snapshot(
        verification_payload(payment_summary={"plan": {"raw": "object"}, "saldo": "100"})
    )

    assert snapshot["payment"]["saldo"] == "100.00"
    assert snapshot["payment"]["plan_label"] is None
    assert "[object Object]" not in str(snapshot["payment"])


def test_address_formatter_omits_missing_values_and_technical_object():
    payload = verification_payload()

    address = bridge_address_from_payload(payload)

    assert address == "Cadereyta de Montes, Col. Sombrerete, C.P. 76536"
    assert "{" not in address
    assert "None" not in address


def test_incomplete_address_returns_no_disponible_for_renderer_compat():
    payload = verification_payload(customer={"address": {"full": None, "city": None}})

    assert bridge_address_from_payload(payload) == "No disponible"


def test_cache_upsert_persists_no_cuenta_snapshot():
    session = DummySession()
    session.extra_json = {}

    upsert_cached_verification(session, "16809", verification_payload(), raw=verification_payload())
    cached = get_cached_verification(session, "16809")

    assert cached["no_cuenta"] == "60436"
    assert session.extra_json["siga_bridge"]["verification_cache"]["snapshot"]["no_cuenta"] == "60436"


def test_cache_hit_does_not_call_bridge():
    session = DummySession()
    session.extra_json = {}
    upsert_cached_verification(session, "16809", verification_payload(), raw=verification_payload())

    class FailingClient:
        async def get_verification(self, folio, company_id=None):
            raise AssertionError("bridge should not be called")

    snapshot = run(get_or_fetch_verification(session, "16809", bridge_client=FailingClient()))

    assert snapshot["no_cuenta"] == "60436"


def test_cache_miss_calls_bridge(monkeypatch):
    session = DummySession()
    session.extra_json = {}
    monkeypatch.setattr("app.services.siga_bridge_cache.settings.SIGA_BRIDGE_ENABLED", True)

    class BridgeClient:
        calls = 0

        async def get_verification(self, folio, company_id=None):
            self.calls += 1
            return verification_payload(sale={"folio": "16809", "no_cuenta": "99999"})

    client = BridgeClient()

    snapshot = run(get_or_fetch_verification(session, "16809", bridge_client=client))

    assert client.calls == 1
    assert snapshot["no_cuenta"] == "99999"


def test_expired_cache_refreshes(monkeypatch):
    session = DummySession()
    session.extra_json = {}
    upsert_cached_verification(
        session,
        "16809",
        verification_payload(sale={"folio": "16809", "no_cuenta": "11111"}),
        ttl_seconds=-1,
    )
    monkeypatch.setattr("app.services.siga_bridge_cache.settings.SIGA_BRIDGE_ENABLED", True)

    class BridgeClient:
        async def get_verification(self, folio, company_id=None):
            return verification_payload(sale={"folio": "16809", "no_cuenta": "22222"})

    snapshot = run(get_or_fetch_verification(session, "16809", bridge_client=BridgeClient()))

    assert snapshot["no_cuenta"] == "22222"


def test_renderer_never_sends_raw_address_dict():
    session = DummySession()
    session.extra_json = {}
    upsert_cached_verification(session, "16809", verification_payload(), raw=verification_payload())

    reply, _buttons, _image_id = render_state(ChatState.CONFIRMAR_DOMICILIO, session, db=None)

    assert "Cadereyta" in reply
    assert "{" not in reply
    assert "[object Object]" not in reply


def test_renderer_bridge_pagos_uses_fecha_venta_for_first_payment():
    session = DummySession()
    session.extra_json = {}
    payload = verification_payload(
        sale={
            "folio": "16809",
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "fecha_venta": "2026-04-30",
        },
        payment_summary={
            "pago_minimo": "215",
            "importe_quincenal": "466",
            "importe_mensual": "932",
        },
    )
    upsert_cached_verification(session, "16809", payload, raw=payload)

    reply, _buttons, _image_id = render_state(ChatState.INFO_PAGOS, session, db=None)

    assert "7 de mayo del 2026" in reply
    assert "Por ahora no tengo disponible el detalle de tu plan de pagos" not in reply


def test_renderer_bridge_plan_3_meses_uses_fecha_venta_base():
    session = DummySession()
    session.extra_json = {}
    payload = verification_payload(
        sale={
            "folio": "16809",
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "fecha_venta": "2026-04-30",
        },
        payment_summary={
            "saldo_3_meses": "7800",
            "importe_semanal_3m": "600",
        },
    )
    upsert_cached_verification(session, "16809", payload, raw=payload)

    reply, _buttons, _image_id = render_state(ChatState.INFO_PLAN_3_MESES, session, db=None)

    assert "30 de julio del 2026" in reply
    assert "$7800.00" in reply
    assert "$600.00" in reply


def test_renderer_bridge_uses_payment_plans_when_bridge_omits_plan_amounts():
    session = DummySession()
    session.extra_json = {}
    payload = verification_payload(
        sale={
            "folio": "16809",
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "fecha_venta": "2026-04-30",
            "pago": "699",
        },
        payment_summary={},
    )
    upsert_cached_verification(session, "16809", payload, raw=payload)

    pagos_reply, _buttons, _image_id = render_state(ChatState.INFO_PAGOS, session, db=None)
    plan_reply, _buttons, _image_id = render_state(ChatState.INFO_PLAN_3_MESES, session, db=None)

    assert "7 de mayo del 2026" in pagos_reply
    assert "215.00" in pagos_reply
    assert "$466.00" in pagos_reply
    assert "$932.00" in pagos_reply
    assert "No tengo disponible" not in pagos_reply
    assert "30 de julio del 2026" in plan_reply
    assert "$7800.00" in plan_reply
    assert "$600.00" in plan_reply
    assert "No tengo disponible" not in plan_reply


def test_payment_plans_use_bridge_payment_snapshot_values():
    venta = bridge_sale_from_payload(
        verification_payload(
            sale={
                "folio": "16809",
                "fecha_venta": "2026-04-30",
                "pago": "699",
            },
            payment_summary={
                "pago_minimo": "230",
                "importe_quincenal": "500",
                "importe_mensual": "1000",
                "saldo_3_meses": "7800",
                "importe_semanal_3m": "600",
                "subsidio": "100",
            },
        )
    )

    pagos = calcular_info_pagos(venta)
    plan_3m = calcular_info_plan_3_meses(venta)

    assert pagos["fecha_limite"] == "7 de mayo del 2026"
    assert pagos["pago_minimo"] == "230.00"
    assert pagos["importe_quincenal"] == "500.00"
    assert pagos["importe_mensual"] == "1000.00"
    assert plan_3m["fecha_limite_3_meses"] == "30 de julio del 2026"
    assert plan_3m["saldo_3_meses"] == "7800.00"
    assert plan_3m["importe_semanal_3m"] == "600.00"
    assert plan_3m["subsidio"] == "100.00"


def test_payment_plans_calculate_bridge_amounts_when_snapshot_omits_them():
    venta = bridge_sale_from_payload(
        verification_payload(
            sale={
                "folio": "16809",
                "fecha_venta": "2026-04-30",
                "pago": "699",
            },
            payment_summary={},
        )
    )

    pagos = calcular_info_pagos(venta)
    plan_3m = calcular_info_plan_3_meses(venta)

    assert pagos["fecha_limite"] == "7 de mayo del 2026"
    assert pagos["pago_minimo"] == "215.00"
    assert pagos["importe_quincenal"] == "466.00"
    assert pagos["importe_mensual"] == "932.00"
    assert plan_3m["fecha_limite_3_meses"] == "30 de julio del 2026"
    assert plan_3m["saldo_3_meses"] == "7800.00"
    assert plan_3m["importe_semanal_3m"] == "600.00"


def test_tracker_marks_bridge_verification_progress_from_cached_snapshot(monkeypatch):
    session = DummySession()
    session.extra_json = {}
    upsert_cached_verification(session, "16809", verification_payload(), raw=verification_payload())
    calls = []

    class FakeVerificationService:
        def __init__(self, db):
            pass

        def mark_step_from_folio(self, *args, **kwargs):
            return None

        def update_step_atomic(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "app.services.verification_tracker.VerificationService",
        FakeVerificationService,
    )

    track_verification(
        db=object(),
        session=session,
        current_state=ChatState.CONFIRMAR_NOMBRE,
        detected_intent="affirmative",
    )

    assert calls == [
        {
            "no_cuenta": "60436",
            "step": "folio",
            "value": 1,
            "phone": "524421234567",
            "event_id": None,
        },
        {
            "no_cuenta": "60436",
            "step": "nombre",
            "value": 1,
            "phone": "524421234567",
            "event_id": None,
        },
    ]
