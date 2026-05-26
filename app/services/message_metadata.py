from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse


def _clean_text(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text[:limit] if text else None


def _button_title(button: dict[str, Any]) -> str | None:
    return _clean_text(
        button.get("title")
        or button.get("label")
        or button.get("text")
        or button.get("reply", {}).get("title")
    )


def build_outgoing_interactive_metadata(
    body: str | None,
    buttons: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    clean_buttons = []
    for button in (buttons or [])[:10]:
        if not isinstance(button, dict):
            continue
        title = _button_title(button)
        button_id = _clean_text(button.get("id") or button.get("reply", {}).get("id"), limit=120)
        if not title and not button_id:
            continue
        clean_buttons.append({
            "id": button_id,
            "title": title or "Opcion",
        })

    if not clean_buttons:
        return None

    return {
        "interactive": {
            "type": "button",
            "body": _clean_text(body, limit=4000) or "",
            "buttons": clean_buttons,
        }
    }


def build_interactive_reply_metadata(
    *,
    reply_type: str | None,
    reply_id: str | None,
    title: str | None,
) -> dict[str, Any] | None:
    if not reply_id and not title:
        return None
    return {
        "interactive_reply": {
            "type": reply_type or "button_reply",
            "id": _clean_text(reply_id, limit=120),
            "title": _clean_text(title, limit=500),
        }
    }


def safe_local_media_url(source: str | None) -> str | None:
    if not source:
        return None
    parsed = urlparse(str(source).strip())
    path = parsed.path if parsed.scheme or parsed.netloc else str(source).strip()
    marker = "/media/"
    if marker not in path:
        return None

    relative = path.split(marker, 1)[1].lstrip("/")
    safe_parts = PurePosixPath(relative).parts
    if not safe_parts or any(part in {"", ".", ".."} for part in safe_parts):
        return None
    return f"/media/{'/'.join(safe_parts)}"


def media_type_from_source(source: str | None) -> str | None:
    text = str(source or "").lower().split("?", 1)[0]
    if text.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    if text.endswith((".mp4", ".mov", ".webm")):
        return "video"
    if text.endswith(".pdf"):
        return "document"
    return None


def build_outgoing_media_metadata(
    *,
    source: str | None,
    caption: str | None = None,
    media_type: str | None = None,
) -> dict[str, Any] | None:
    resolved_type = media_type or media_type_from_source(source)
    if not resolved_type:
        return None

    local_url = safe_local_media_url(source)
    payload: dict[str, Any] = {
        "type": resolved_type,
        "caption": _clean_text(caption, limit=1000),
    }
    if local_url:
        payload["url"] = local_url
    else:
        payload["status"] = "sent_without_local_preview"

    return {"media": {key: value for key, value in payload.items() if value is not None}}


def merge_message_metadata(*items: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged or None
