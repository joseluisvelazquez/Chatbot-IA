import pytest
from app.core.flow_engine import process_message
from app.core.states import ChatState


class FakeSession:
    def __init__(self, state, previous_state=None):
        self.state = state
        self.previous_state = previous_state


def test_binary_affirmative_transition():
    session = FakeSession(ChatState.CONFIRMAR_NOMBRE.value)

    reply, next_state, buttons, prev = process_message(
        session=session,
        text="sí",
        intent=None,
    )

    assert next_state == ChatState.CONFIRMAR_DOMICILIO


def test_binary_ambiguous():
    session = FakeSession(ChatState.CONFIRMAR_NOMBRE.value)

    reply, next_state, buttons, prev = process_message(
        session=session,
        text="si no",
        intent=None,
    )

    assert next_state == ChatState.CONFIRMAR_NOMBRE
    assert "Solo necesito" in reply


def test_resume_previous_state():
    session = FakeSession(
        state=ChatState.ACLARACION.value,
        previous_state=ChatState.CONFIRMAR_DOMICILIO.value,
    )

    reply, next_state, buttons, prev = process_message(
        session=session,
        text="continuar",
        intent="ACLARA_CONTINUAR",
    )

    assert next_state == ChatState.CONFIRMAR_DOMICILIO


def test_out_of_flow_ai_respond(monkeypatch):
    from app.core import flow_engine

    session = FakeSession(ChatState.CONFIRMAR_NOMBRE.value)

    def fake_ai(session, text):
        return {
            "action": "respond",
            "reply": "respuesta IA",
            "next_state": None,
        }

    monkeypatch.setattr(flow_engine, "handle_out_of_flow", fake_ai)

    reply, next_state, buttons, prev = flow_engine.process_message(
        session=session,
        text="quiero cancelar",
        intent=None,
    )

    assert reply == "respuesta IA"
    assert next_state == ChatState.CONFIRMAR_NOMBRE

