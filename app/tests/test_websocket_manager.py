import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.services import panel_notifications
from app.services.panel_notifications import publish_chat_operation
from app.websockets.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.closed = False

    async def send_json(self, payload):
        self.messages.append(payload)

    async def close(self, code=1000):
        self.closed = True


def user(role, username):
    return SimpleNamespace(role=role, username=username)


def chat(**overrides):
    values = {
        "id": 7,
        "phone": "5214270000000",
        "test_mode": False,
        "owner_type": "user",
        "assigned_role": "gestor_cobranza",
        "assigned_user_id": "gestor1",
        "previous_owner_user_id": None,
        "status_operativo": "assigned_gestor",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_chat_transition_sends_removal_to_users_that_lost_visibility():
    async def scenario():
        manager = ConnectionManager()
        old_owner_ws = FakeWebSocket()
        new_owner_ws = FakeWebSocket()
        admin_ws = FakeWebSocket()
        unrelated_ws = FakeWebSocket()

        await manager.connect(old_owner_ws, user("gestor_cobranza", "gestor1"))
        await manager.connect(new_owner_ws, user("gestor_cobranza", "gestor2"))
        await manager.connect(admin_ws, user("admin", "admin"))
        await manager.connect(unrelated_ws, user("gestor_cobranza", "gestor3"))

        before_chat = chat().__dict__.copy()
        after_chat = chat(assigned_user_id="gestor2")

        await manager.send_chat_transition(
            before_chat=before_chat,
            after_chat=after_chat,
            build_message=lambda raw_user: {
                "type": "chat_operation",
                "payload": {
                    "id": 7,
                    "viewer": raw_user.username,
                },
            },
            build_removal_message=lambda _raw_user: {
                "type": "conversation_removed",
                "payload": {
                    "session_id": 7,
                },
            },
        )

        assert old_owner_ws.messages[-1]["type"] == "conversation_removed"
        assert old_owner_ws.messages[-1]["payload"]["session_id"] == 7

        assert new_owner_ws.messages[-1]["type"] == "chat_operation"
        assert new_owner_ws.messages[-1]["payload"]["viewer"] == "gestor2"

        assert admin_ws.messages[-1]["type"] == "chat_operation"
        assert unrelated_ws.messages == []

    asyncio.run(scenario())


class FakeNotificationManager:
    def __init__(self):
        self.transition_calls = 0
        self.user_notifications = []
        self.role_notifications = []
        self.admin_notifications = []

    async def send_chat_transition(self, **_kwargs):
        self.transition_calls += 1

    async def send_to_user(self, username, message):
        self.user_notifications.append((username, message))

    async def send_to_role(self, role, message):
        self.role_notifications.append((role, message))

    async def send_to_admins(self, message):
        self.admin_notifications.append(message)


def operation_result(**overrides):
    values = {
        "chat": chat(),
        "before_chat": None,
        "event": SimpleNamespace(
            event_id="event-1",
            created_at=datetime(2026, 1, 1),
        ),
        "notification_target_user": None,
        "notification_target_role": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_direct_assignment_notification_does_not_fan_out_to_whole_role(monkeypatch):
    async def scenario():
        fake_manager = FakeNotificationManager()
        monkeypatch.setattr(panel_notifications, "manager", fake_manager)

        await publish_chat_operation(
            operation_result(
                notification_target_user="GESTOR1",
                notification_target_role="gestor_cobranza",
            )
        )

        assert fake_manager.transition_calls == 1
        assert [item[0] for item in fake_manager.user_notifications] == ["GESTOR1"]
        assert fake_manager.role_notifications == []

    asyncio.run(scenario())


def test_queue_assignment_notification_still_goes_to_target_role(monkeypatch):
    async def scenario():
        fake_manager = FakeNotificationManager()
        monkeypatch.setattr(panel_notifications, "manager", fake_manager)

        await publish_chat_operation(
            operation_result(
                notification_target_user=None,
                notification_target_role="soporte_tecnico",
            )
        )

        assert fake_manager.transition_calls == 1
        assert fake_manager.user_notifications == []
        assert [item[0] for item in fake_manager.role_notifications] == ["soporte_tecnico"]

    asyncio.run(scenario())
