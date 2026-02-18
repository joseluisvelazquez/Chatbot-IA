import pytest
from app.core.flow_engine import process_message
from app.core.states import ChatState


def test_binary_affirmative_transition():
    reply, next_state, buttons, prev, document = process_message(
        state=ChatState.CONFIRMAR_NOMBRE.value,
        text="sí",
        intent=None,
    )

    assert next_state == ChatState.CONFIRMAR_DOMICILIO
    assert document is None


def test_binary_ambiguous():
    reply, next_state, buttons, prev, document = process_message(
        state=ChatState.CONFIRMAR_NOMBRE.value,
        text="si no",
        intent=None,
    )

    assert next_state == ChatState.CONFIRMAR_NOMBRE
    assert "Sí o No" in reply
    assert document is None


def test_resume_previous_state():
    reply, next_state, buttons, prev, document = process_message(
        state=ChatState.ACLARACION.value,
        text="continuar",
        intent="REANUDACION",
        previous_state=ChatState.CONFIRMAR_DOMICILIO.value,
    )

    assert next_state == ChatState.CONFIRMAR_DOMICILIO
    assert document is None


def test_out_of_flow_ai_respond(monkeypatch):
    from app.core import flow_engine

    def fake_ai(state, text):
        return {
            "action": "respond",
            "reply": "respuesta IA",
            "next_state": None,
        }

    monkeypatch.setattr(flow_engine, "handle_out_of_flow", fake_ai)

    reply, next_state, buttons, prev, document = flow_engine.process_message(
        state=ChatState.CONFIRMAR_NOMBRE.value,
        text="quiero cancelar",
        intent=None,
    )

    assert reply == "respuesta IA"
    assert next_state == ChatState.CONFIRMAR_NOMBRE
    assert document is None
