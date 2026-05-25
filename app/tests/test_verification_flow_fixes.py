from app.core.flow import flow_engine
from app.api.external import _parse_payload
from app.core.states.state_renderer import render_state
from app.core.states.states import ChatState
from app.services.siga_navigation import build_siga_account_url


class DummySession:
    id = 123
    phone = "524421234567"
    last_message_id = "wamid.test"

    def __init__(self):
        self.folio = "1111"
        self.state = ChatState.MENU_AYUDA.value
        self.previous_state = ChatState.CONFIRMAR_PRODUCTO.value
        self.extra_json = {
            "siga_bridge": {
                "verification_cache": {
                    "folio": "1111",
                    "snapshot": {"folio": "1111", "no_cuenta": "OLD"},
                },
                "verification_lookup": {
                    "folio": "1111",
                    "data": {"folio": "1111", "no_cuenta": "OLD"},
                },
            }
        }
        self.invalid_folio_attempts = 2


class EmptyQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class EmptyDb:
    def query(self, *args, **kwargs):
        return EmptyQuery()


def bridge_payload(folio="2222"):
    return {
        "found": True,
        "source_table": "bitacora_ventas",
        "sale": {
            "folio": folio,
            "no_cuenta": "60436",
            "sku_bitacora_v": "PC-MAXICA",
            "descripcion": "CPU INTEL COREI3+ / AMD A4+, SSD 120GB",
        },
        "customer": {"nombre": "CLIENTE DEMO"},
        "account": {"no_cuenta": "60436"},
        "payment_summary": {},
    }


def test_try_mark_step_ignores_inicio_without_touching_store(monkeypatch):
    class FailingVerificationService:
        def __init__(self, db):
            raise AssertionError("inicio must not instantiate VerificationService")

    monkeypatch.setattr(flow_engine, "VerificationService", FailingVerificationService)

    flow_engine._try_mark_step(object(), DummySession(), "inicio")


def test_new_explicit_folio_replaces_previous_context():
    session = DummySession()
    session.previous_state = None

    result = flow_engine.process_message(
        session=session,
        text="Mi numero de folio es 2222",
        db=EmptyDb(),
        bridge_verification=bridge_payload("2222"),
    )

    assert result.next_state == ChatState.INICIO2
    assert session.folio == "2222"
    assert session.previous_state is None
    assert session.invalid_folio_attempts == 0
    assert session.extra_json["siga_bridge"]["verification_cache"]["folio"] == "2222"


def test_initial_prefilled_activation_message_starts_bridge_verification():
    session = DummySession()
    session.state = ChatState.ESPERA.value
    session.previous_state = None
    session.folio = None
    session.extra_json = {}

    result = flow_engine.process_message(
        session=session,
        text="Hola MEXIcomp, adquirí un equipo y quiero activar mis beneficios, mi folio es: 17726",
        db=EmptyDb(),
        bridge_verification=bridge_payload("17726"),
    )

    assert result.next_state == ChatState.INICIO2
    assert session.folio == "17726"
    assert "Cliente Demo" in result.reply


def test_active_menu_blocks_new_folio_without_replacing_bridge_cache():
    session = DummySession()

    result = flow_engine.process_message(
        session=session,
        text="mi folio es 2222",
        db=EmptyDb(),
        bridge_verification=bridge_payload("2222"),
    )

    assert result.next_state == ChatState.MENU_AYUDA
    assert session.folio == "1111"
    assert session.extra_json["siga_bridge"]["verification_cache"]["folio"] == "1111"
    assert "verificación activa" in result.reply


def test_renderer_blocks_inicio_without_sale_snapshot():
    session = DummySession()
    session.state = ChatState.INICIO.value
    session.folio = "3333"
    session.extra_json = {}

    reply, buttons, _image_id = render_state(ChatState.INICIO, session, EmptyDb())

    assert "{nombre_completo}" not in reply
    assert "preparando la informacion" in reply
    assert buttons == []


def test_continuation_does_not_advance_without_snapshot():
    session = DummySession()
    session.state = ChatState.INICIO.value
    session.folio = "3333"
    session.extra_json = {}

    result = flow_engine.process_message(
        session=session,
        text="si",
        db=EmptyDb(),
    )

    assert result.next_state == ChatState.INICIO
    assert "{nombre_completo}" not in result.reply
    assert "preparando la informacion" in result.reply


def test_external_trigger_normalizes_mexico_phone_and_folio():
    data = _parse_payload({"phone": "442 123 4567", "folio": "16779"})

    assert data.phone == "5214421234567"
    assert data.folio == "16779"


def test_siga_account_url_uses_legacy_entry_page(monkeypatch):
    monkeypatch.setattr("app.services.siga_navigation.settings.SIGA_PANEL_BASE_URL", "https://siga.mxcomp.mx/")
    monkeypatch.setattr("app.services.siga_navigation.settings.SIGA_ACCOUNT_REDIRECT_PATH", "cuentas.php")

    url = build_siga_account_url(no_cuenta="60436", folio="16809")

    assert url == "https://siga.mxcomp.mx/cuentas.php"
    assert "60436" not in url


def test_metodos_pago_advances_to_comprobante_access_state():
    session = DummySession()
    session.state = ChatState.INFO_METODOS_PAGO.value
    session.previous_state = ChatState.INFO_METODOS_PAGO.value
    session.extra_json = {
        "siga_bridge": {
            "verification_cache": {
                "folio": "1111",
                "snapshot": {
                    "found": True,
                    "folio": "1111",
                    "no_cuenta": "60436",
                    "codigo_cliente": "CLI-123",
                    "customer": {"codigo_cliente": "CLI-123"},
                    "sale": {"folio": "1111", "no_cuenta": "60436"},
                },
            }
        }
    }

    result = flow_engine.process_message(
        session=session,
        text="",
        intent="PAGOS_OK",
        db=None,
    )

    assert result.next_state == ChatState.INFO_COMPROBANTE_ACCESO
    assert "Número de cuenta: *A60436*" in result.reply
    assert "Código de cliente: *CLI-123*" in result.reply
    assert result.buttons == [{"id": "COMPROBANTE_ACCESO_OK", "label": "✅ Entendido"}]


def test_info_pagos_no_doubt_text_advances_without_ai(monkeypatch):
    session = DummySession()
    session.state = ChatState.INFO_PAGOS.value
    session.previous_state = ChatState.INFO_PAGOS.value
    session.extra_json = {
        "siga_bridge": {
            "verification_cache": {
                "folio": "1111",
                "snapshot": {
                    "found": True,
                    "folio": "1111",
                    "no_cuenta": "60436",
                    "sale": {"folio": "1111", "no_cuenta": "60436", "fecha_venta": "2026-04-30"},
                },
            }
        }
    }

    def fail_ai(*_args, **_kwargs):
        raise AssertionError("no-doubt confirmation must not invoke AI")

    monkeypatch.setattr(flow_engine, "interpret_intent_with_ai", fail_ai)
    monkeypatch.setattr(flow_engine, "generate_ai_response", fail_ai)

    result = flow_engine.process_message(
        session=session,
        text="no tengo dudas",
        db=None,
    )

    assert result.next_state == ChatState.INFO_METODOS_PAGO


def test_info_pagos_plain_no_advances_as_no_doubts(monkeypatch):
    session = DummySession()
    session.state = ChatState.INFO_PAGOS.value
    session.previous_state = ChatState.INFO_PAGOS.value
    session.extra_json = {
        "siga_bridge": {
            "verification_cache": {
                "folio": "1111",
                "snapshot": {
                    "found": True,
                    "folio": "1111",
                    "no_cuenta": "60436",
                    "sale": {"folio": "1111", "no_cuenta": "60436", "fecha_venta": "2026-04-30"},
                },
            }
        }
    }

    def fail_ai(*_args, **_kwargs):
        raise AssertionError("plain no in info state must not invoke AI")

    monkeypatch.setattr(flow_engine, "interpret_intent_with_ai", fail_ai)
    monkeypatch.setattr(flow_engine, "generate_ai_response", fail_ai)

    result = flow_engine.process_message(
        session=session,
        text="no",
        db=None,
    )

    assert result.next_state == ChatState.INFO_METODOS_PAGO


def test_comprobante_access_button_advances_to_plan_3_meses():
    session = DummySession()
    session.state = ChatState.INFO_COMPROBANTE_ACCESO.value
    session.previous_state = ChatState.INFO_COMPROBANTE_ACCESO.value

    result = flow_engine.process_message(
        session=session,
        text="",
        intent="COMPROBANTE_ACCESO_OK",
        db=None,
    )

    assert result.next_state == ChatState.INFO_PLAN_3_MESES


def test_comprobante_access_doubt_uses_ai_without_inconsistency(monkeypatch):
    session = DummySession()
    session.state = ChatState.INFO_COMPROBANTE_ACCESO.value
    session.previous_state = ChatState.INFO_COMPROBANTE_ACCESO.value
    session.extra_json = {
        "siga_bridge": {
            "verification_cache": {
                "folio": "1111",
                "snapshot": {
                    "found": True,
                    "folio": "1111",
                    "no_cuenta": "60436",
                    "codigo_cliente": "CLI-123",
                    "customer": {"codigo_cliente": "CLI-123"},
                    "sale": {"folio": "1111", "no_cuenta": "60436"},
                },
            }
        }
    }

    def fake_ai(*_args, **_kwargs):
        return "Puedes usar esos datos para ingresar al sitio de comprobantes."

    def fail_inconsistency(*_args, **_kwargs):
        raise AssertionError("comprobante access doubts must not create inconsistencies")

    monkeypatch.setattr(flow_engine, "find_faq_answer", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(flow_engine, "generate_ai_response", fake_ai)
    monkeypatch.setattr(flow_engine, "analyze_inconsistency", fail_inconsistency)

    result = flow_engine.process_message(
        session=session,
        text="Tengo una duda",
        db=None,
    )

    assert result.next_state == ChatState.MENU_AYUDA
    assert "Puedes usar esos datos" in result.reply
    assert not result.inconsistencia_patch
