from datetime import datetime
from typing import Optional, Dict, Any

from app.services.message_metadata import build_interactive_reply_metadata
from app.utils.timezone import mexico_from_unix_timestamp


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).replace("\x00", "").strip()
    return text[:4000] if text else None


def _clean_phone(value: Any) -> str | None:
    if value is None:
        return None

    phone = "".join(ch for ch in str(value) if ch.isdigit())
    return phone or None


def _fallback_text_for_message_type(message_type: str | None) -> str:
    labels = {
        "interactive": "Respuesta interactiva recibida",
        "button": "Boton recibido",
        "image": "Imagen recibida",
        "document": "Documento recibido",
        "video": "Video recibido",
        "audio": "Audio recibido",
        "sticker": "Sticker recibido",
    }
    return labels.get(str(message_type or "unknown").lower(), "Mensaje recibido")


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        if value is None:
            return None

        return mexico_from_unix_timestamp(value)
    except (TypeError, ValueError, OSError):
        return None


def parse_meta_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convierte el payload de WhatsApp Cloud API en un formato universal.
    NUNCA rompe el webhook.
    """

    try:
        entry = payload.get("entry")
        if not entry:
            return None

        changes = entry[0].get("changes")
        if not changes:
            return None

        value = changes[0].get("value", {})

        # --------------------------------------------------
        # STATUS EVENTS (sent, delivered, read)
        # --------------------------------------------------
        if "statuses" in value:
            return {
                "phone": None,
                "message_id": None,
                "type": "status",
                "text": None,
                "button_id": None,
                "media_id": None,
                "file_name": None,
                "is_status": True,
                "unsupported": False,
            }

        messages = value.get("messages")
        if not messages:
            return None

        message = messages[0]

        phone = _clean_phone(message.get("from"))
        message_id = _clean_text(message.get("id"))
        message_type = message.get("type")
        timestamp = _parse_timestamp(message.get("timestamp"))

        text = None
        button_id = None
        media_id = None
        file_name = None
        unsupported = False
        caption = None
        metadata = None

        # --------------------------------------------------
        # TEXT
        # --------------------------------------------------
        if message_type == "text":
            text = _clean_text(message.get("text", {}).get("body"))

        # --------------------------------------------------
        # TEMPLATE / LEGACY BUTTON
        # --------------------------------------------------
        elif message_type == "button":
            button = message.get("button", {})
            button_text = _clean_text(button.get("text"))
            button_id = _clean_text(button.get("payload"))
            text = button_text or _fallback_text_for_message_type(message_type)
            metadata = build_interactive_reply_metadata(
                reply_type="button_reply",
                reply_id=button_id,
                title=button_text,
            )

        # --------------------------------------------------
        # BUTTONS / LISTS
        # --------------------------------------------------
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            i_type = interactive.get("type")

            if i_type == "button_reply":
                reply = interactive.get("button_reply", {})
                button_id = _clean_text(reply.get("id"))
                title = _clean_text(reply.get("title"))
                text = title or _fallback_text_for_message_type(message_type)
                metadata = build_interactive_reply_metadata(
                    reply_type="button_reply",
                    reply_id=button_id,
                    title=title,
                )

            elif i_type == "list_reply":
                reply = interactive.get("list_reply", {})
                button_id = _clean_text(reply.get("id"))
                title = _clean_text(reply.get("title"))
                text = title or _fallback_text_for_message_type(message_type)
                metadata = build_interactive_reply_metadata(
                    reply_type="list_reply",
                    reply_id=button_id,
                    title=title,
                )

        # --------------------------------------------------
        # IMAGE ✅
        # --------------------------------------------------
        elif message_type == "image":
            image = message.get("image", {})
            media_id = _clean_text(image.get("id"))
            caption = _clean_text(image.get("caption"))

        # --------------------------------------------------
        # DOCUMENT ✅
        # --------------------------------------------------
        elif message_type == "document":
            document = message.get("document", {})
            media_id = _clean_text(document.get("id"))
            file_name = _clean_text(document.get("filename"))
            caption = _clean_text(document.get("caption"))

        # --------------------------------------------------
        # OTROS (audio, video, sticker, etc.)
        # --------------------------------------------------
        else:
            unsupported = True

        return {
            "phone": phone,
            "message_id": message_id,
            "type": message_type,
            "text": text or caption or _fallback_text_for_message_type(message_type),
            "button_id": button_id,
            "media_id": media_id,
            "file_name": file_name,
            "extra_json": metadata,
            "timestamp": timestamp,
            "is_status": False,
            "unsupported": unsupported,
        }

    except Exception:
        return None
