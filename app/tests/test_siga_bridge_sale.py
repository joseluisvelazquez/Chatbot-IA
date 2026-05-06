import asyncio

from app.core.states.state_renderer import render_state
from app.core.states.states import ChatState
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
