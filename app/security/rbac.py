from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import and_, or_

from app.db.models import ChatSessions


ROLE_ADMIN = "admin"
ROLE_JEFE_OPERATIVO = "jefe_operativo"
ROLE_GESTOR_COBRANZA = "gestor_cobranza"
ROLE_SOPORTE_TECNICO = "soporte_tecnico"
ROLE_LECTURA = "lectura"

FINAL_PANEL_ROLES = {
    ROLE_ADMIN,
    ROLE_JEFE_OPERATIVO,
    ROLE_GESTOR_COBRANZA,
    ROLE_SOPORTE_TECNICO,
    ROLE_LECTURA,
}

LEGACY_ROLE_MAP = {
    "ventas": ROLE_LECTURA,
    "cobranza": ROLE_GESTOR_COBRANZA,
    "sistemas": ROLE_SOPORTE_TECNICO,
    "viewer": ROLE_LECTURA,
    "supervisor": ROLE_LECTURA,
}

TEST_PHONE_ONLY = {
    "5214271227177",
    "5214271665615",
    "5214271644542",
}

PERMISSIONS_BY_ROLE: dict[str, set[str]] = {
    ROLE_ADMIN: {
        "testing:use",
        "feature_flags:write",
        "metrics:view",
        "chat:view_all",
        "chat:read",
        "chat:reply_any",
        "chat:take",
        "chat:release",
        "chat:transfer_any",
        "chat:bulk_reassign",
        "chat:reset",
        "chat:assign_manager",
    },
    ROLE_JEFE_OPERATIVO: {
        "metrics:view",
        "chat:view_all",
        "chat:read",
        "chat:take",
        "chat:release",
        "chat:transfer_any",
        "chat:bulk_reassign",
        "chat:assign_manager",
    },
    ROLE_GESTOR_COBRANZA: {
        "chat:read",
        "chat:reply_owned",
        "chat:take",
        "chat:release_owned",
        "chat:transfer_owned",
        "chat:return_assistant",
        "accounts:assigned",
    },
    ROLE_SOPORTE_TECNICO: {
        "chat:read",
        "chat:take",
        "chat:reply_owned",
        "chat:release_owned",
        "chat:transfer_owned",
        "chat:return_assistant",
        "chat:return_original_gestor",
        "technical:close",
    },
    ROLE_LECTURA: {
        "chat:read",
        "metrics:view",
    },
}


def normalize_role(role: str | None) -> str:
    value = str(role or "").strip().lower()
    return LEGACY_ROLE_MAP.get(value, value if value in FINAL_PANEL_ROLES else ROLE_LECTURA)


def is_admin(user) -> bool:
    return normalize_role(getattr(user, "role", None)) == ROLE_ADMIN


def has_permission(user, permission: str) -> bool:
    role = normalize_role(getattr(user, "role", None))
    return permission in PERMISSIONS_BY_ROLE.get(role, set())


def require_permission(user, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado",
        )


def normalize_phone(phone: str | None) -> str:
    return str(phone or "").replace("+", "").replace(" ", "").strip()


def normalize_username(value: str | None) -> str:
    return str(value or "").strip().upper()


def is_test_phone(phone: str | None) -> bool:
    return normalize_phone(phone) in TEST_PHONE_ONLY


def is_test_chat(chat: ChatSessions) -> bool:
    return bool(getattr(chat, "test_mode", False) or is_test_phone(chat.phone))


def assert_can_access_test_chat(chat: ChatSessions, user) -> None:
    if is_test_chat(chat) and not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesion no encontrada",
        )


def status_for_role(role: str | None) -> str:
    normalized = normalize_role(role)
    if normalized == ROLE_GESTOR_COBRANZA:
        return "assigned_gestor"
    if normalized == ROLE_SOPORTE_TECNICO:
        return "assigned_soporte"
    if normalized == ROLE_JEFE_OPERATIVO:
        return "escalated"
    return "assigned_gestor"


def chat_status(chat: ChatSessions) -> str:
    return str(getattr(chat, "status_operativo", None) or "assistant_active").strip().lower()


def chat_assigned_role(chat: ChatSessions) -> str | None:
    raw_role = getattr(chat, "assigned_role", None)
    return normalize_role(raw_role) if raw_role else None


def chat_assigned_user(chat: ChatSessions) -> str:
    return normalize_username(getattr(chat, "assigned_user_id", None))


def chat_previous_owner(chat: ChatSessions) -> str:
    return normalize_username(getattr(chat, "previous_owner_user_id", None))


def actor_username(user) -> str:
    return normalize_username(getattr(user, "username", None))


def is_assigned_to_user(chat: ChatSessions, user) -> bool:
    username = actor_username(user)
    return bool(username and chat_assigned_user(chat) == username)


def is_previous_owner(chat: ChatSessions, user) -> bool:
    username = actor_username(user)
    return bool(username and chat_previous_owner(chat) == username)


def is_role_queue(chat: ChatSessions, role: str) -> bool:
    return not chat_assigned_user(chat) and chat_assigned_role(chat) == normalize_role(role)


def is_closed_chat(chat: ChatSessions) -> bool:
    return chat_status(chat) == "closed"


def owner_matches_user(chat: ChatSessions, user) -> bool:
    username = actor_username(user)
    role = normalize_role(getattr(user, "role", None))
    assigned_user_id = chat_assigned_user(chat)
    assigned_role = chat_assigned_role(chat)

    if assigned_user_id and assigned_user_id == username:
        return True

    return not assigned_user_id and assigned_role == role


def reply_owner_matches_user(chat: ChatSessions, user) -> bool:
    username = actor_username(user)
    assigned_user_id = chat_assigned_user(chat)
    return bool(username and assigned_user_id and assigned_user_id == username)


def can_view_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if role == ROLE_ADMIN:
        return True

    if role == ROLE_JEFE_OPERATIVO:
        return True

    if role == ROLE_LECTURA:
        return True

    if role == ROLE_GESTOR_COBRANZA:
        if status_operativo in {"assigned_gestor", "waiting_customer", "closed"}:
            return is_assigned_to_user(chat, user)

        if status_operativo == "assistant_active":
            return is_assigned_to_user(chat, user) or (
                getattr(chat, "owner_type", None) == "assistant"
                and not chat_assigned_user(chat)
            )

        if status_operativo == "assigned_soporte":
            # lectura histórica para el gestor original; no reply
            return is_previous_owner(chat, user)

        # escalated NO lo ve gestor
        return False

    if role == ROLE_SOPORTE_TECNICO:
        if status_operativo == "assigned_soporte":
            return is_assigned_to_user(chat, user) or is_role_queue(chat, ROLE_SOPORTE_TECNICO)

        if status_operativo == "closed":
            return is_assigned_to_user(chat, user)

        # soporte no ve escalados, gestor ni assistant
        return False

    return False


def can_reply_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if is_closed_chat(chat):
        return False

    if role == ROLE_ADMIN:
        return True

    if role == ROLE_LECTURA:
        return False

    if role == ROLE_JEFE_OPERATIVO:
        return reply_owner_matches_user(chat, user)

    if role == ROLE_GESTOR_COBRANZA:
        return (
            status_operativo in {"assigned_gestor", "waiting_customer", "assistant_active"}
            and reply_owner_matches_user(chat, user)
        )

    if role == ROLE_SOPORTE_TECNICO:
        return (
            status_operativo == "assigned_soporte"
            and chat_assigned_role(chat) == ROLE_SOPORTE_TECNICO
            and reply_owner_matches_user(chat, user)
        )

    return False


def can_take_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if is_closed_chat(chat) or not has_permission(user, "chat:take"):
        return False

    if role == ROLE_ADMIN:
        return True

    if role == ROLE_JEFE_OPERATIVO:
        if is_assigned_to_user(chat, user):
            return True

        if status_operativo in {"unassigned", "assistant_active"}:
            return not chat_assigned_user(chat)

        if status_operativo == "escalated":
            return is_role_queue(chat, ROLE_JEFE_OPERATIVO) or not chat_assigned_user(chat)

        return False

    if role == ROLE_GESTOR_COBRANZA:
        if status_operativo in {"assigned_gestor", "waiting_customer"}:
            return is_role_queue(chat, ROLE_GESTOR_COBRANZA)
        if status_operativo == "assistant_active":
            return (
                getattr(chat, "owner_type", None) == "assistant"
                and not chat_assigned_user(chat)
            )
        return False

    if role == ROLE_SOPORTE_TECNICO:
        if status_operativo == "assigned_soporte":
            return is_role_queue(chat, ROLE_SOPORTE_TECNICO)
        return False

    return False


def can_assign_manager_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if role not in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO}:
        return False

    if is_closed_chat(chat):
        return False

    if chat_status(chat) == "assigned_soporte":
        return False

    return can_view_chat(chat, user)


def can_transfer_to_support_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if status_operativo in {"assigned_soporte", "closed", "escalated"}:
        return False

    if role in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO}:
        return can_view_chat(chat, user)

    if role == ROLE_GESTOR_COBRANZA:
        return can_reply_chat(chat, user)

    return False


def can_close_support_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if chat_status(chat) != "assigned_soporte" or is_closed_chat(chat):
        return False

    if role == ROLE_ADMIN:
        return True

    if role == ROLE_JEFE_OPERATIVO:
        return True

    if role == ROLE_SOPORTE_TECNICO:
        return is_assigned_to_user(chat, user)

    return False


def can_return_to_gestor_chat(chat: ChatSessions, user) -> bool:
    return can_close_support_chat(chat, user) and bool(chat_previous_owner(chat))


def can_return_to_assistant_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if status_operativo == "closed":
        return False

    if status_operativo == "assigned_soporte":
        return can_close_support_chat(chat, user)

    if status_operativo == "assistant_active":
        return False

    if role in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO}:
        return can_view_chat(chat, user)

    if role == ROLE_GESTOR_COBRANZA:
        return can_reply_chat(chat, user)

    return False


def can_escalate_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if status_operativo in {"closed", "escalated"}:
        return False

    if role == ROLE_ADMIN:
        return can_view_chat(chat, user)

    if role == ROLE_GESTOR_COBRANZA:
        return can_reply_chat(chat, user)

    if role == ROLE_SOPORTE_TECNICO:
        return can_close_support_chat(chat, user)

    return False


def can_release_chat(chat: ChatSessions, user) -> bool:
    role = normalize_role(getattr(user, "role", None))
    status_operativo = chat_status(chat)

    if is_test_chat(chat):
        return role == ROLE_ADMIN

    if status_operativo == "closed":
        return False

    if status_operativo == "assigned_soporte":
        return can_close_support_chat(chat, user)

    if role in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO}:
        return can_view_chat(chat, user)

    if role == ROLE_GESTOR_COBRANZA:
        return can_reply_chat(chat, user)

    return False


def build_chat_permission_flags(chat: ChatSessions, user) -> dict[str, bool]:
    if not can_view_chat(chat, user):
        return {
            "can_reply": False,
            "can_take": False,
            "can_transfer": False,
            "can_assign_manager": False,
            "can_transfer_to_support": False,
            "can_return_to_gestor": False,
            "can_return_to_assistant": False,
            "can_escalate": False,
            "can_release": False,
            "can_close_support": False,
            "has_pending_action": False,
        }

    can_reply = can_reply_chat(chat, user)
    can_take = can_take_chat(chat, user)
    can_assign_manager = can_assign_manager_chat(chat, user)
    can_transfer_to_support = can_transfer_to_support_chat(chat, user)
    can_return_to_gestor = can_return_to_gestor_chat(chat, user)
    can_return_to_assistant = can_return_to_assistant_chat(chat, user)
    can_escalate = can_escalate_chat(chat, user)
    can_release = can_release_chat(chat, user)
    can_close_support = can_close_support_chat(chat, user)

    can_transfer = any(
        [
            can_transfer_to_support,
            can_return_to_gestor,
            can_return_to_assistant,
            can_escalate,
        ]
    )

    status_operativo = chat_status(chat)

    queued_for_take = (
        can_take
        and not chat_assigned_user(chat)
        and status_operativo in {
            "assistant_active",
            "assigned_soporte",
            "escalated",
            "unassigned",
        }
    )

    queued_for_assignment = (
        can_assign_manager
        and not chat_assigned_user(chat)
        and status_operativo in {
            "assistant_active",
            "escalated",
            "unassigned",
        }
    )

    has_pending_action = queued_for_take or queued_for_assignment or (
        bool(getattr(chat, "transfer_pending", False))
        and any(
            [
                can_reply,
                can_take,
                can_assign_manager,
                can_transfer_to_support,
                can_return_to_gestor,
                can_return_to_assistant,
                can_escalate,
                can_release,
                can_close_support,
            ]
        )
    )

    return {
        "can_reply": can_reply,
        "can_take": can_take,
        "can_transfer": can_transfer,
        "can_assign_manager": can_assign_manager,
        "can_transfer_to_support": can_transfer_to_support,
        "can_return_to_gestor": can_return_to_gestor,
        "can_return_to_assistant": can_return_to_assistant,
        "can_escalate": can_escalate,
        "can_release": can_release,
        "can_close_support": can_close_support,
        "has_pending_action": has_pending_action,
    }


def ensure_can_view_chat(chat: ChatSessions, user) -> None:
    if not can_view_chat(chat, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesion no encontrada",
        )


def ensure_can_reply_chat(chat: ChatSessions, user) -> None:
    ensure_can_view_chat(chat, user)
    if not can_reply_chat(chat, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes responder esta conversacion con el owner actual",
        )


def apply_test_visibility_filter(query, user):
    if is_admin(user):
        return query

    return query.filter(
        or_(
            ChatSessions.test_mode.is_(False),
            ChatSessions.test_mode.is_(None),
        )
    )


def apply_chat_visibility_filter(query, user):
    role = normalize_role(getattr(user, "role", None))
    username = actor_username(user)

    query = apply_test_visibility_filter(query, user)

    if role in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO, ROLE_LECTURA}:
        return query

    if role == ROLE_GESTOR_COBRANZA:
        return query.filter(
            or_(
                and_(
                    ChatSessions.status_operativo.in_(
                        [
                            "assigned_gestor",
                            "waiting_customer",
                            "closed",
                            "assistant_active",
                        ]
                    ),
                    ChatSessions.assigned_user_id == username,
                ),
                and_(
                    ChatSessions.status_operativo == "assigned_soporte",
                    ChatSessions.previous_owner_user_id == username,
                ),
                and_(
                    ChatSessions.status_operativo == "assistant_active",
                    ChatSessions.owner_type == "assistant",
                    ChatSessions.assigned_user_id.is_(None),
                ),
            )
        )

    if role == ROLE_SOPORTE_TECNICO:
        return query.filter(
            or_(
                and_(
                    ChatSessions.status_operativo == "assigned_soporte",
                    ChatSessions.assigned_user_id == username,
                ),
                and_(
                    ChatSessions.status_operativo == "assigned_soporte",
                    ChatSessions.assigned_role == ROLE_SOPORTE_TECNICO,
                    ChatSessions.assigned_user_id.is_(None),
                ),
                and_(
                    ChatSessions.status_operativo == "closed",
                    ChatSessions.assigned_user_id == username,
                ),
            )
        )

    return query.filter(False)


def require_any_role(user, allowed_roles: Iterable[str]) -> None:
    normalized = normalize_role(getattr(user, "role", None))
    if normalized not in {normalize_role(role) for role in allowed_roles}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado",
        )
