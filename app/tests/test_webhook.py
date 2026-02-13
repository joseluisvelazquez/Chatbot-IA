import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.states import ChatState


client = TestClient(app)


class FakeSession:
    def __init__(self):
        self.id = 1
        self.state = ChatState.CONFIRMAR_NOMBRE.value
        self.previous_state = None


def test_webhook_success(monkeypatch):

    # 🔥 Fake session
    fake_session = FakeSession()

    def fake_get_or_create(phone):
        return fake_session

    def fake_process_message(session, text, intent):
        return (
            "respuesta de prueba",
            ChatState.CONFIRMAR_DOMICILIO,
            [{"id": "TEST", "label": "Test"}],
            None,
        )

    def fake_update_session(session_id, state, last_message, previous_state=None):
        # Aquí solo validamos que lo llamen
        assert session_id == 1
        assert state == ChatState.CONFIRMAR_DOMICILIO.value
        assert last_message == "sí"

    # 🔥 Monkeypatch correcto (parchear donde se usa)
    monkeypatch.setattr(
        "app.api.webhook.get_or_create_session",
        fake_get_or_create,
    )

    monkeypatch.setattr(
        "app.api.webhook.process_message",
        fake_process_message,
    )

    monkeypatch.setattr(
        "app.api.webhook.update_session",
        fake_update_session,
    )

    response = client.post(
        "/webhook",
        json={
            "phone": "1234567890",
            "state": ChatState.CONFIRMAR_NOMBRE.value,
            "text": "sí",
            "button_id": None,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reply"] == "respuesta de prueba"
    assert data["next_state"] == ChatState.CONFIRMAR_DOMICILIO.value
    assert data["buttons"] == [{"id": "TEST", "label": "Test"}]
def test_webhook_invalid_state():

    response = client.post(
        "/webhook",
        json={
            "phone": "1234567890",
            "state": "ESTADO_INVALIDO",
            "text": "hola",
            "button_id": None,
        },
    )

    assert response.status_code == 422
