from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.chat_operations import _ensure_can_take


def chat(**overrides):
    values = {
        "phone": "5214270000000",
        "test_mode": False,
        "owner_type": "user",
        "assigned_user_id": "GESTOR1",
        "assigned_role": "gestor_cobranza",
        "status_operativo": "assigned_gestor",
        "previous_owner_user_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user(role, username):
    return SimpleNamespace(role=role, username=username)


def test_readonly_user_gets_forbidden_when_trying_to_take_visible_chat():
    with pytest.raises(HTTPException) as exc_info:
        _ensure_can_take(chat(), user("lectura", "VIEWER1"))

    assert exc_info.value.status_code == 403


def test_operational_user_gets_conflict_when_visible_chat_has_other_owner():
    with pytest.raises(HTTPException) as exc_info:
        _ensure_can_take(chat(), user("jefe_operativo", "JEFE_PANEL"))

    assert exc_info.value.status_code == 409
