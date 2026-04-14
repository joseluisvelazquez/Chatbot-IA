from typing import Optional, Dict, Any


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

        phone = message.get("from")
        message_id = message.get("id")
        message_type = message.get("type")

        text = None
        button_id = None
        media_id = None
        file_name = None
        unsupported = False
        caption = None

        # --------------------------------------------------
        # TEXT
        # --------------------------------------------------
        if message_type == "text":
            text = message.get("text", {}).get("body")

        # --------------------------------------------------
        # BUTTONS / LISTS
        # --------------------------------------------------
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            i_type = interactive.get("type")

            if i_type == "button_reply":
                button_id = interactive.get("button_reply", {}).get("id")

            elif i_type == "list_reply":
                button_id = interactive.get("list_reply", {}).get("id")

        # --------------------------------------------------
        # IMAGE ✅
        # --------------------------------------------------
        elif message_type == "image":
            image = message.get("image", {})
            media_id = image.get("id")
            caption = image.get("caption")

        # --------------------------------------------------
        # DOCUMENT ✅
        # --------------------------------------------------
        elif message_type == "document":
            document = message.get("document", {})
            media_id = document.get("id")
            file_name = document.get("filename")
            caption = document.get("caption")

        # --------------------------------------------------
        # OTROS (audio, video, sticker, etc.)
        # --------------------------------------------------
        else:
            unsupported = True

        return {
            "phone": phone,
            "message_id": message_id,
            "type": message_type,
            "text": text or caption,
            "button_id": button_id,
            "media_id": media_id,
            "file_name": file_name,
            "is_status": False,
            "unsupported": unsupported,
        }

    except Exception:
        return None