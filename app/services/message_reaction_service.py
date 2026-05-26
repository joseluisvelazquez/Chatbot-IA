from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Message, MessageReaction
from app.utils.timezone import mexico_now_naive


def serialize_reaction(reaction: MessageReaction) -> dict[str, Any]:
    return {
        "id": reaction.id,
        "message_id": reaction.message_id,
        "wa_message_id_original": reaction.wa_message_id_original,
        "reaction_emoji": reaction.reaction_emoji,
        "reacted_by_phone": reaction.reacted_by_phone,
        "created_at": reaction.created_at.isoformat() if reaction.created_at else None,
        "updated_at": reaction.updated_at.isoformat() if reaction.updated_at else None,
    }


def reactions_for_messages(db: Session, message_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    ids = [int(message_id) for message_id in message_ids if message_id]
    if not ids:
        return {}

    rows = (
        db.query(MessageReaction)
        .filter(MessageReaction.message_id.in_(ids))
        .order_by(MessageReaction.updated_at.asc(), MessageReaction.created_at.asc(), MessageReaction.id.asc())
        .all()
    )

    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(int(row.message_id), []).append(serialize_reaction(row))
    return result


def attach_reactions_to_messages(db: Session, messages: list[Message]) -> None:
    grouped = reactions_for_messages(db, [message.id for message in messages if message.id])
    for message in messages:
        setattr(message, "reactions_payload", grouped.get(int(message.id), []))


def upsert_reaction(
    db: Session,
    *,
    target_message: Message,
    wa_message_id_original: str,
    reacted_by_phone: str,
    reaction_emoji: str,
    reacted_at: datetime | None = None,
) -> MessageReaction:
    now = reacted_at or mexico_now_naive()
    existing = (
        db.query(MessageReaction)
        .filter(
            MessageReaction.wa_message_id_original == wa_message_id_original,
            MessageReaction.reacted_by_phone == reacted_by_phone,
        )
        .first()
    )

    if existing:
        existing.message_id = target_message.id
        existing.reaction_emoji = reaction_emoji
        existing.updated_at = now
        return existing

    reaction = MessageReaction(
        message_id=target_message.id,
        wa_message_id_original=wa_message_id_original,
        reaction_emoji=reaction_emoji,
        reacted_by_phone=reacted_by_phone,
        created_at=now,
        updated_at=now,
    )
    db.add(reaction)
    return reaction


def delete_reaction(
    db: Session,
    *,
    wa_message_id_original: str,
    reacted_by_phone: str,
) -> MessageReaction | None:
    existing = (
        db.query(MessageReaction)
        .filter(
            MessageReaction.wa_message_id_original == wa_message_id_original,
            MessageReaction.reacted_by_phone == reacted_by_phone,
        )
        .first()
    )
    if existing:
        db.delete(existing)
    return existing
