from types import SimpleNamespace

from app.security.rbac import (
    build_chat_permission_flags,
    can_reply_chat,
    can_take_chat,
    can_view_chat,
    normalize_role,
)


def chat(**overrides):
    values = {
        "phone": "5214270000000",
        "test_mode": False,
        "owner_type": "assistant",
        "assigned_user_id": None,
        "assigned_role": None,
        "status_operativo": "assistant_active",
        "previous_owner_user_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user(role, username="u1"):
    return SimpleNamespace(role=role, username=username)


def test_legacy_supervisor_does_not_escalate_to_jefe():
    assert normalize_role("supervisor") == "lectura"


def test_role_queue_is_visible_but_not_replyable_until_taken():
    support_user = user("soporte_tecnico", "tech1")
    c = chat(
        owner_type="user",
        assigned_role="soporte_tecnico",
        assigned_user_id=None,
        status_operativo="assigned_soporte",
    )

    assert can_view_chat(c, support_user)
    assert can_take_chat(c, support_user)
    assert not can_reply_chat(c, support_user)

    permissions = build_chat_permission_flags(c, support_user)
    assert permissions["can_take"] is True
    assert permissions["can_reply"] is False
    assert permissions["has_pending_action"] is True


def test_support_owner_blocks_gestor_reply_but_keeps_original_visibility():
    gestor = user("gestor_cobranza", "gestor1")
    c = chat(
        owner_type="user",
        assigned_role="soporte_tecnico",
        assigned_user_id="tech1",
        previous_owner_user_id="gestor1",
        status_operativo="assigned_soporte",
    )

    assert can_view_chat(c, gestor)
    assert not can_reply_chat(c, gestor)


def test_gestor_cannot_view_unrelated_support_chat():
    gestor = user("gestor_cobranza", "gestor1")
    c = chat(
        owner_type="user",
        assigned_role="soporte_tecnico",
        assigned_user_id="tech1",
        previous_owner_user_id="gestor2",
        status_operativo="assigned_soporte",
    )

    assert not can_view_chat(c, gestor)


def test_support_cannot_view_chat_taken_by_other_support_user():
    support_user = user("soporte_tecnico", "tech2")
    c = chat(
        owner_type="user",
        assigned_role="soporte_tecnico",
        assigned_user_id="tech1",
        status_operativo="assigned_soporte",
    )

    assert not can_view_chat(c, support_user)
    assert not can_take_chat(c, support_user)


def test_gestor_cannot_view_escalated_chat():
    gestor = user("gestor_cobranza", "gestor1")
    c = chat(
        owner_type="user",
        assigned_role="jefe_operativo",
        assigned_user_id=None,
        status_operativo="escalated",
    )

    assert not can_view_chat(c, gestor)


def test_gestor_can_view_and_take_unowned_assistant_chat():
    gestor = user("gestor_cobranza", "gestor1")
    c = chat(
        owner_type="assistant",
        assigned_role=None,
        assigned_user_id=None,
        status_operativo="assistant_active",
    )

    assert can_view_chat(c, gestor)
    assert can_take_chat(c, gestor)

    permissions = build_chat_permission_flags(c, gestor)
    assert permissions["can_take"] is True
    assert permissions["can_reply"] is False
    assert permissions["has_pending_action"] is True


def test_gestor_can_view_own_assistant_follow_up():
    gestor = user("gestor_cobranza", "gestor1")
    c = chat(
        owner_type="user",
        assigned_role="gestor_cobranza",
        assigned_user_id="gestor1",
        status_operativo="assistant_active",
    )

    assert can_view_chat(c, gestor)
    assert can_reply_chat(c, gestor)


def test_admin_can_reassign_taken_chat_without_pending_badge():
    admin = user("admin", "boss")
    c = chat(
        owner_type="user",
        assigned_role="gestor_cobranza",
        assigned_user_id="gestor1",
        status_operativo="assigned_gestor",
    )

    permissions = build_chat_permission_flags(c, admin)
    assert permissions["can_assign_manager"] is True
    assert permissions["has_pending_action"] is False


def test_test_chat_is_admin_only():
    c = chat(phone="5214271227177", test_mode=True)

    assert can_view_chat(c, user("admin", "admin"))
    assert not can_view_chat(c, user("jefe_operativo", "boss"))
