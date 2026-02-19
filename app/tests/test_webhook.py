from fastapi.testclient import TestClient
from app.main import app
from app.core.states import ChatState

client = TestClient(app)


class FakeSession:
    id = 1
    state = ChatState.CONFIRMAR_NOMBRE.value
    previous_state = None
    last_message_id = None


def test_webhook_success(monkeypatch):

    fake_session = FakeSession()

    def fake_get_or_create(db, phone):
        return fake_session

    def fake_process_message(state, text, intent, previous_state=None):
        return (
            "respuesta de prueba",
            ChatState.CONFIRMAR_DOMICILIO,
            [{"id": "TEST", "label": "Test"}],
            None,
            None,  # ← document
        )

    def fake_update_session(db, session, state, last_message, previous_state=None, message_id=None):
        assert session.id == 1
        assert state == ChatState.CONFIRMAR_DOMICILIO.value
        assert last_message == "sí"
        assert message_id == "msg-1"

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
            "text": "sí",
            "button_id": None,
            "message_id": "msg-1",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["reply"] == "respuesta de prueba"
    assert data["next_state"] == ChatState.CONFIRMAR_DOMICILIO.value
    assert data["buttons"] == [{"id": "TEST", "label": "Test"}]
