import pytest
from app.core.states.states import ChatState
from app.core.flow import flow_engine
from app.core.states import state_handlers
from app.core.verification.verification_schema import DEFAULT_VERIFICATION_PROGRESS

class DummySession:
    id = 123
    phone = "524421234567"
    last_message_id = "wamid.test"
    ai_intent_attempts = 0
    ai_response_attempts = 0
    ai_inconsistency_attempts = 0
    invalid_folio_attempts = 0

    def __init__(self):
        self.folio = "1111"
        self.state = ChatState.CONFIRMAR_DOMICILIO.value
        self.previous_state = ChatState.CONFIRMAR_NOMBRE.value
        self.extra_json = {}


class DummyVerificacionCuenta:
    def __init__(self):
        self.no_cuenta = "60436"
        self.json = DEFAULT_VERIFICATION_PROGRESS.copy()
        self.version = 0


class DummyQuery:
    def __init__(self, item=None):
        self.item = item

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.item

    def notin_(self, *args):
        return self


class DummyDb:
    def __init__(self, verificacion=None):
        self.verificacion = verificacion or DummyVerificacionCuenta()
        self.flushed = False
        self.committed = False
        self.added = []

    def query(self, model):
        from app.db.models import VerificacionCuenta, ChatSessions
        if model == VerificacionCuenta:
            return DummyQuery(self.verificacion)
        return DummyQuery()

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flushed = True

    def commit(self):
        self.committed = True


def test_classify_doubt_to_info_state():
    # Probar que clasifica por palabras clave correctamente
    assert flow_engine._classify_doubt_to_info_state("dónde puedo pagar?") == ChatState.INFO_METODOS_PAGO
    assert flow_engine._classify_doubt_to_info_state("subir mi comprobante de pago") == ChatState.INFO_COMPROBANTE_ACCESO
    assert flow_engine._classify_doubt_to_info_state("cómo es el plan de 3 meses") == ChatState.INFO_PLAN_3_MESES


def test_verification_service_allow_out_of_order():
    db = DummyDb()
    from app.services.verification_service import VerificationService, VerificationTransitionError
    
    service = VerificationService(db)
    
    # Intentar marcar un paso futuro (ej: bancos) cuando previos están incompletos
    # Sin allow_out_of_order debe fallar
    with pytest.raises(VerificationTransitionError):
        service.update_step_atomic(
            no_cuenta="60436",
            step="bancos",
            value=1,
            allow_out_of_order=False
        )

    # Con allow_out_of_order debe tener éxito
    res = service.update_step_atomic(
        no_cuenta="60436",
        step="bancos",
        value=1,
        allow_out_of_order=True
    )
    assert res.progress["bancos"] == 1
    assert db.flushed is True


def test_flow_engine_doubt_jump_ahead_transition(monkeypatch):
    session = DummySession()
    db = DummyDb()

    # Simulamos que detecta intent = doubt
    monkeypatch.setattr(flow_engine, "detect_intent", lambda text, state: ("doubt", "1111"))
    monkeypatch.setattr(flow_engine, "is_doubt", lambda text: True)
    monkeypatch.setattr(flow_engine, "should_use_ai", lambda *args: False)
    monkeypatch.setattr(flow_engine, "obtener_venta_por_folio", lambda *args: object())

    # Enviamos una duda sobre bancos
    result = flow_engine.process_message(
        session=session,
        text="dónde realizo mi pago?",
        db=db
    )

    # Debe haber transicionado al estado INFO_METODOS_PAGO
    assert result.next_state == ChatState.INFO_METODOS_PAGO
    assert session.state == ChatState.INFO_METODOS_PAGO.value
    # Debe haber guardado el estado de origen en extra_json
    assert session.extra_json["verification_suspended_state"] == ChatState.CONFIRMAR_DOMICILIO.value


def test_flow_engine_pop_state_restoration(monkeypatch):
    session = DummySession()
    session.state = ChatState.INFO_METODOS_PAGO.value
    session.previous_state = ChatState.CONFIRMAR_DOMICILIO.value
    session.extra_json = {"verification_suspended_state": ChatState.CONFIRMAR_DOMICILIO.value}
    
    db = DummyDb()

    monkeypatch.setattr(flow_engine, "detect_intent", lambda text, state: ("PAGOS_OK", None))
    monkeypatch.setattr(flow_engine, "obtener_venta_por_folio", lambda *args: object())

    # El usuario presiona el botón de confirmación ("Está claro") en INFO_METODOS_PAGO
    result = flow_engine.process_message(
        session=session,
        text="PAGOS_OK",
        intent="PAGOS_OK",
        db=db
    )

    # Debe haber registrado el paso 'bancos' como 1
    assert db.verificacion.json["bancos"] == 1
    # Debe haber retirado el suspended_state del extra_json
    assert "verification_suspended_state" not in session.extra_json
    # Debe haber retornado al estado suspendido CONFIRMAR_DOMICILIO
    assert result.next_state == ChatState.CONFIRMAR_DOMICILIO
    assert session.state == ChatState.CONFIRMAR_DOMICILIO.value


def test_handle_flow_skips_dynamic():
    db = DummyDb()
    # Marcamos 'bancos' (INFO_METODOS_PAGO) como completado (1) en la base de datos
    db.verificacion.json["bancos"] = 1

    class MockContext:
        def __init__(self):
            self.db = db
            self.folio = "1111"
            self.venta = object()
            self.phone = "524421234567"
            self.session = DummySession()

    context = MockContext()

    # Si el siguiente estado es INFO_METODOS_PAGO, debe saltarlo automáticamente
    # y avanzar al siguiente estado que es INFO_COMPROBANTE_ACCESO
    next_state = state_handlers.handle_flow_skips(context, ChatState.INFO_METODOS_PAGO)
    assert next_state == ChatState.INFO_COMPROBANTE_ACCESO
