from app.core.flow import flow_engine
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
    assert "siga_bridge" not in session.extra_json


def test_siga_account_url_uses_legacy_entry_page(monkeypatch):
    monkeypatch.setattr("app.services.siga_navigation.settings.SIGA_PANEL_BASE_URL", "https://siga.mxcomp.mx/")
    monkeypatch.setattr("app.services.siga_navigation.settings.SIGA_ACCOUNT_REDIRECT_PATH", "cuentas.php")

    url = build_siga_account_url(no_cuenta="60436", folio="16809")

    assert url == "https://siga.mxcomp.mx/cuentas.php"
    assert "60436" not in url
