from __future__ import annotations

import asyncio

from app.db.models import ChatSessions
from app.security.rbac import (
    ROLE_ADMIN,
    ROLE_JEFE_OPERATIVO,
    ROLE_SOPORTE_TECNICO,
    build_chat_permission_flags,
)
from app.services.panel_events import event_envelope
from app.websockets.manager import manager


def _iso(value):
    return value.isoformat() if value else None


def conversation_operational_payload(chat: ChatSessions, user=None) -> dict:
    payload = {
        "id": chat.id,
        "session_id": chat.id,
        "phone": chat.phone,
        "folio": str(chat.folio) if chat.folio else None,
        "last_message": chat.last_message,
        "last_message_at": _iso(chat.last_message_at),
        "unread_count": int(chat.unread_count or 0),

        "owner_type": chat.owner_type,
        "assigned_user_id": chat.assigned_user_id,
        "assigned_role": chat.assigned_role,

        "status_operativo": chat.status_operativo,
        "priority": chat.priority,

        "transfer_pending": bool(chat.transfer_pending),
        "locked_until": _iso(chat.locked_until),
        "assigned_at": _iso(chat.assigned_at),

        "last_agent_message_at": _iso(chat.last_agent_message_at),
        "last_customer_message_at": _iso(chat.last_customer_message_at),

        "returned_from_role": chat.returned_from_role,

        "transferred_by_user_id": getattr(chat, "transferred_by_user_id", None),
        "previous_owner_user_id": getattr(chat, "previous_owner_user_id", None),
        "previous_owner_role": getattr(chat, "previous_owner_role", None),
        "transfer_reason": getattr(chat, "transfer_reason", None),
        "transfer_created_at": _iso(getattr(chat, "transfer_created_at", None)),

        "test_mode": bool(chat.test_mode),

        "requires_human": bool(chat.transfer_pending)
        or chat.status_operativo in {
            "unassigned",
            "escalated",
        },
    }

    if user is not None:
        payload.update(build_chat_permission_flags(chat, user))

    return payload


async def publish_chat_operation(result) -> None:
    chat = result.chat
    before_chat = result.before_chat or None

    await manager.send_chat_transition(
        before_chat=before_chat,
        after_chat=chat,
        build_message=lambda context: event_envelope(
            result.event,
            "chat_operation",
            conversation_operational_payload(chat, user=context),
        ),
        build_removal_message=lambda _context: {
            "type": "conversation_removed",
            "payload": {
                "session_id": chat.id,
            },
        },
    )

    if bool(chat.test_mode):
        await manager.send_to_admins({
            "type": "notification",
            "payload": {
                "kind": "chat_test_mode",
                "session_id": chat.id,
                "phone": chat.phone,
                "status_operativo": chat.status_operativo,
            },
        })
        return

    tasks = []

    if result.notification_target_user:
        tasks.append(
            manager.send_to_user(
                result.notification_target_user,
                {
                    "type": "notification",
                    "payload": {
                        "kind": "chat_assigned",
                        "session_id": chat.id,
                        "phone": chat.phone,
                        "status_operativo": chat.status_operativo,
                    },
                },
            )
        )

    if result.notification_target_role and not result.notification_target_user:
        tasks.append(
            manager.send_to_role(
                result.notification_target_role,
                {
                    "type": "notification",
                    "payload": {
                        "kind": "chat_role_queue",
                        "session_id": chat.id,
                        "phone": chat.phone,
                        "status_operativo": chat.status_operativo,
                    },
                },
            )
        )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def publish_new_customer_message(
    chat: ChatSessions,
    message_payload: dict,
) -> None:
    notification_payload = {
        "kind": "new_customer_message",
        "session_id": chat.id,
        "phone": chat.phone,
        "conversation": conversation_operational_payload(chat),
        "message": message_payload,
    }

    realtime_task = manager.send_to_chat_watchers_personalized(
        chat,
        lambda context: {
            "type": "new_message",
            "session_id": chat.id,
            "phone": chat.phone,
            "conversation": conversation_operational_payload(
                chat,
                user=context,
            ),
            "message": message_payload,
            "unread_count": int(chat.unread_count or 0),
        },
    )

    notify_task = None

    if bool(chat.test_mode):
        notify_task = manager.send_to_admins({
            "type": "notification",
            "payload": notification_payload,
        })

    elif chat.assigned_user_id:
        notify_task = manager.send_to_user(
            chat.assigned_user_id,
            {
                "type": "notification",
                "payload": notification_payload,
            },
        )

    elif chat.assigned_role:
        notify_task = manager.send_to_role(
            chat.assigned_role,
            {
                "type": "notification",
                "payload": notification_payload,
            },
        )

    else:
        notify_task = manager.send_to_role(
            ROLE_JEFE_OPERATIVO,
            {
                "type": "notification",
                "payload": notification_payload,
            },
        )

    await asyncio.gather(
        realtime_task,
        notify_task,
        return_exceptions=True,
    )


async def publish_technical_signal(
    chat: ChatSessions,
    keyword: str | None,
) -> None:
    payload = {
        "kind": "technical_signal",
        "session_id": chat.id,
        "phone": chat.phone,
        "keyword": keyword,
        "status_operativo": chat.status_operativo,
        "priority": chat.priority,
        "transfer_pending": bool(chat.transfer_pending),
    }

    if bool(chat.test_mode):
        await manager.send_to_admins({
            "type": "notification",
            "payload": payload,
        })
        return

    await asyncio.gather(
        manager.send_to_role(
            ROLE_SOPORTE_TECNICO,
            {"type": "notification", "payload": payload},
        ),
        manager.send_to_role(
            ROLE_JEFE_OPERATIVO,
            {"type": "notification", "payload": payload},
        ),
        manager.send_to_role(
            ROLE_ADMIN,
            {"type": "notification", "payload": payload},
        ),
        return_exceptions=True,
    )
