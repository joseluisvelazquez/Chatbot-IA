from __future__ import annotations

from datetime import datetime
from typing import Any


def iso_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return None
    return str(value)


def preview_text(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)].rstrip()}..."


def strip_undefined(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def chat_name_from_bridge_cache(chat: Any) -> str | None:
    extra = getattr(chat, "extra_json", None)
    if not isinstance(extra, dict):
        return None
    siga_bridge = extra.get("siga_bridge")
    if not isinstance(siga_bridge, dict):
        return None

    snapshot = None
    cache = siga_bridge.get("verification_cache")
    if isinstance(cache, dict) and isinstance(cache.get("snapshot"), dict):
        snapshot = cache["snapshot"]
    lookup = siga_bridge.get("verification_lookup")
    if snapshot is None and isinstance(lookup, dict) and isinstance(lookup.get("data"), dict):
        snapshot = lookup["data"]

    customer = snapshot.get("customer") if isinstance(snapshot, dict) and isinstance(snapshot.get("customer"), dict) else {}
    name = customer.get("name") if isinstance(customer, dict) else None
    text = str(name or "").strip()
    return text or None


def build_message_payload(message: Any) -> dict[str, Any]:
    return {
        "id": getattr(message, "id", None),
        "message_id": getattr(message, "message_id", None),
        "phone": getattr(message, "phone", None),
        "content": getattr(message, "content", None),
        "direction": getattr(message, "direction", None),
        "created_at": iso_datetime(getattr(message, "created_at", None)) or "",
        "type": getattr(message, "type", None),
        "media_url": getattr(message, "media_url", None),
        "file_name": getattr(message, "file_name", None),
        "extra_json": getattr(message, "extra_json", None),
        "reactions": getattr(message, "reactions_payload", None) or [],
    }


def build_conversation_payload(chat: Any, message: Any | None = None) -> dict[str, Any]:
    message_created_at = iso_datetime(getattr(message, "created_at", None)) if message else None
    message_content = getattr(message, "content", None) if message else None
    last_message = message_content if message_content not in (None, "") else getattr(chat, "last_message", None)
    if not last_message and message is not None and getattr(message, "media_url", None):
        last_message = getattr(message, "file_name", None) or "Archivo adjunto"

    return {
        "id": getattr(chat, "id", None),
        "session_id": getattr(chat, "id", None),
        "phone": getattr(chat, "phone", None),
        "name": chat_name_from_bridge_cache(chat),
        "last_message": last_message or "",
        "last_message_at": message_created_at or iso_datetime(getattr(chat, "last_message_at", None)) or "",
        "last_customer_message_at": iso_datetime(getattr(chat, "last_customer_message_at", None)),
        "unread_count": getattr(chat, "unread_count", 0) or 0,
        "folio": str(getattr(chat, "folio", "")) if getattr(chat, "folio", None) else None,
        "status": getattr(chat, "state", None),
    }


def build_new_message_event(chat: Any, message: Any) -> dict[str, Any]:
    message_payload = build_message_payload(message)
    conversation = build_conversation_payload(chat, message)
    message_id = message_payload.get("message_id") or message_payload.get("id")
    preview = preview_text(
        message_payload.get("content")
        or message_payload.get("file_name")
        or conversation.get("last_message")
    )

    return {
        "type": "new_message",
        "session_id": getattr(chat, "id", None),
        "message_id": message_id,
        "message_kind": message_payload.get("type") or "text",
        "direction": message_payload.get("direction"),
        "created_at": message_payload.get("created_at"),
        "preview": preview,
        "conversation_patch": {
            "last_message": conversation.get("last_message"),
            "last_message_at": conversation.get("last_message_at"),
            "unread_count": conversation.get("unread_count"),
        },
        # Campos legacy que ya consume el panel actual.
        "phone": getattr(chat, "phone", None),
        "conversation": conversation,
        "message": message_payload,
        "unread_count": conversation.get("unread_count"),
    }


def build_reaction_update_event(
    *,
    session_id: int | None,
    wa_message_id_original: str | None,
    message_id: int | None = None,
    reaction: dict[str, Any] | None = None,
    removed: bool = False,
    orphan: bool = False,
    event_message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = strip_undefined({
        "session_id": session_id,
        "message_id": message_id,
        "wa_message_id_original": wa_message_id_original,
        "reaction": reaction,
        "removed": removed,
        "orphan": orphan,
        "event_message": event_message,
    })
    return {
        "type": "reaction_update",
        "session_id": session_id,
        "message_id": message_id,
        "payload": payload,
    }


def build_conversation_updated_event(
    chat: Any,
    *,
    patch: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    base_patch = {
        "folio": str(getattr(chat, "folio", "")) if getattr(chat, "folio", None) else None,
        "status": getattr(chat, "state", None),
        "unread_count": getattr(chat, "unread_count", 0) or 0,
        "last_message": getattr(chat, "last_message", None),
        "last_message_at": iso_datetime(getattr(chat, "last_message_at", None)),
        "updated_at": iso_datetime(getattr(chat, "updated_at", None))
        or iso_datetime(getattr(chat, "last_message_at", None)),
    }
    if patch:
        base_patch.update(patch)

    payload = {
        "session_id": getattr(chat, "id", None),
        **base_patch,
        "source": source,
    }
    return {
        "type": "conversation_updated",
        "session_id": getattr(chat, "id", None),
        "patch": base_patch,
        "payload": payload,
    }


def minimal_verification_payload(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None

    siga = snapshot.get("siga") if isinstance(snapshot.get("siga"), dict) else {}
    siga_bridge = snapshot.get("siga_bridge") if isinstance(snapshot.get("siga_bridge"), dict) else {}
    return {
        "session_id": snapshot.get("session_id"),
        "verification_id": snapshot.get("verification_id"),
        "folio": snapshot.get("folio"),
        "no_cuenta": snapshot.get("no_cuenta"),
        "phone": snapshot.get("phone"),
        "name": snapshot.get("name"),
        "status": snapshot.get("status"),
        "state": snapshot.get("status"),
        "progress_pct": snapshot.get("progress_pct"),
        "progress": snapshot.get("progress_pct"),
        "current_step": snapshot.get("current_step"),
        "last_activity": snapshot.get("last_activity"),
        "inconsistencias_count": snapshot.get("inconsistencias_count"),
        "has_inconsistency": bool(snapshot.get("inconsistencias_count") or 0),
        "inconsistencias": snapshot.get("inconsistencias"),
        "severity_counts": snapshot.get("severity_counts"),
        "highest_severity": snapshot.get("highest_severity"),
        "confirmed_count": snapshot.get("confirmed_count"),
        "total_steps": snapshot.get("total_steps"),
        "session_state": snapshot.get("session_state"),
        "previous_state": snapshot.get("previous_state"),
        "siga_url": snapshot.get("siga_url"),
        "siga": {
            "available": bool(siga.get("available")),
            "fetched_at": siga.get("fetched_at"),
            "source_table": siga.get("source_table"),
            "cache_valid": siga.get("cache_valid"),
        } if siga else None,
        "siga_bridge": {
            "enabled": bool(siga_bridge.get("enabled")),
            "available": bool(siga_bridge.get("available")),
            "status": siga_bridge.get("status"),
            "source": siga_bridge.get("source"),
            "updated_at": siga_bridge.get("updated_at"),
        } if siga_bridge else None,
    }


def build_verification_updated_event(
    snapshot: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any] | None:
    payload = minimal_verification_payload(snapshot)
    if not payload or not payload.get("session_id"):
        return None

    patch = {
        "verification_id": payload.get("verification_id"),
        "folio": payload.get("folio"),
        "no_cuenta": payload.get("no_cuenta"),
        "state": payload.get("state"),
        "current_step": payload.get("current_step"),
        "progress_pct": payload.get("progress_pct"),
        "progress": payload.get("progress"),
        "has_inconsistency": payload.get("has_inconsistency"),
        "last_activity": payload.get("last_activity"),
    }

    return {
        "type": "verification_updated",
        "session_id": payload.get("session_id"),
        "folio": payload.get("folio"),
        "no_cuenta": payload.get("no_cuenta"),
        "status": payload.get("status"),
        "updated_at": payload.get("last_activity") or "",
        "source": source,
        "patch": patch,
        "payload": payload,
    }


def build_verification_context_changed_event(
    chat: Any,
    snapshot: dict[str, Any] | None = None,
    *,
    previous_folio: str | None = None,
    source: str | None = None,
    force_refetch: bool = True,
) -> dict[str, Any] | None:
    session_id = getattr(chat, "id", None)
    if not session_id:
        return None

    current_folio = str(getattr(chat, "folio", "")) if getattr(chat, "folio", None) else None
    payload = minimal_verification_payload(snapshot)
    if payload and payload.get("folio") and current_folio and str(payload.get("folio")) != current_folio:
        payload = None

    progress = payload.get("progress_pct") if payload else None
    body = strip_undefined({
        "session_id": session_id,
        "folio": current_folio,
        "previous_folio": previous_folio,
        "verification_id": payload.get("verification_id") if payload else None,
        "no_cuenta": payload.get("no_cuenta") if payload else None,
        "current_step": payload.get("current_step") if payload else None,
        "progress_pct": progress,
        "progress": progress,
        "state": payload.get("state") if payload else getattr(chat, "state", None),
        "last_activity": payload.get("last_activity") if payload else iso_datetime(getattr(chat, "last_message_at", None)),
        "updated_at": payload.get("last_activity") if payload else iso_datetime(getattr(chat, "updated_at", None)),
        "force_refetch": force_refetch,
        "source": source,
    })

    return {
        "type": "verification_context_changed",
        **body,
        "payload": body,
    }


def build_siga_snapshot_updated_event(
    snapshot: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any] | None:
    payload = minimal_verification_payload(snapshot)
    if not payload or not payload.get("session_id"):
        return None

    updated_at = None
    if isinstance(payload.get("siga"), dict):
        updated_at = payload["siga"].get("fetched_at")
    if not updated_at and isinstance(payload.get("siga_bridge"), dict):
        updated_at = payload["siga_bridge"].get("updated_at")

    return {
        "type": "siga_snapshot_updated",
        "session_id": payload.get("session_id"),
        "folio": payload.get("folio"),
        "no_cuenta": payload.get("no_cuenta"),
        "updated_at": updated_at or payload.get("last_activity") or "",
        "source": source,
        "payload": payload,
    }


def _inconsistency_field(inc: Any) -> str | None:
    extra = getattr(inc, "extra_json", None)
    if not isinstance(extra, dict):
        return None
    for key in ("campo", "field", "estado_origen"):
        if extra.get(key):
            return str(extra[key])
    items = extra.get("inconsistencias")
    if isinstance(items, list) and items:
        last_item = items[-1]
        if isinstance(last_item, dict):
            return last_item.get("campo") or last_item.get("estado_origen")
    return None


def build_inconsistency_created_event(inc: Any) -> dict[str, Any]:
    status = str(getattr(inc, "estatus", "") or "ABIERTA")
    return {
        "type": "inconsistency_created",
        "session_id": getattr(inc, "session_id", None),
        "inconsistency_id": getattr(inc, "id", None),
        "folio": getattr(inc, "folio", None),
        "field": _inconsistency_field(inc),
        "status": status,
        "created_at": iso_datetime(getattr(inc, "created_at", None)) or "",
    }


def build_inconsistency_updated_event(
    inc: Any,
    *,
    source: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(getattr(inc, "estatus", "") or "")
    body = payload or {}
    return {
        "type": "inconsistency_updated",
        "session_id": getattr(inc, "session_id", None),
        "inconsistency_id": getattr(inc, "id", None),
        "status": status,
        "updated_at": iso_datetime(getattr(inc, "updated_at", None))
        or iso_datetime(getattr(inc, "created_at", None))
        or "",
        "source": source,
        "payload": {
            "id": getattr(inc, "id", None),
            "session_id": getattr(inc, "session_id", None),
            "status": status,
            **body,
        },
    }
