from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import PanelDomainEvent


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def emit_domain_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str | int | None = None,
    actor=None,
    payload: dict[str, Any] | None = None,
) -> PanelDomainEvent:
    event = PanelDomainEvent(
        event_id=uuid4().hex,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id) if aggregate_id is not None else None,
        actor_username=getattr(actor, "username", None),
        actor_role=getattr(actor, "role", None),
        payload=payload or {},
        created_at=utcnow_naive(),
    )
    db.add(event)
    db.flush()
    return event


def event_envelope(event: PanelDomainEvent, event_type: str | None = None, payload: dict | None = None) -> dict:
    created_at = event.created_at or utcnow_naive()
    return {
        "event_id": event.event_id,
        "type": event_type or event.event_type,
        "payload": payload if payload is not None else (event.payload or {}),
        "created_at": created_at.isoformat(),
    }
