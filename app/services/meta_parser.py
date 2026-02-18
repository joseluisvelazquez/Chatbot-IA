from typing import Optional, Dict, Any


def parse_meta_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Traduce el payload crudo de WhatsApp Cloud API a una estructura simple.

    Devuelve:
    {
        "phone": str,
        "text": Optional[str],
        "button_id": Optional[str],
        "is_status": bool
    }

    Retorna None si el payload no contiene un mensaje procesable.
    """

    try:
        entry = payload.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})

        # ----------------------------------------------------
        # 1. Detectar eventos de estado (message status)
        # ----------------------------------------------------
        if "statuses" in value:
            return {
                "phone": None,
                "text": None,
                "button_id": None,
                "is_status": True,
            }

        # ----------------------------------------------------
        # 2. Validar que haya mensajes
        # ----------------------------------------------------
        messages = value.get("messages")
        if not messages:
            return None

        message = messages[0]
        phone = message.get("from")

        text = None
        button_id = None

        message_type = message.get("type")

        # ----------------------------------------------------
        # 3. Mensaje de texto normal
        # ----------------------------------------------------
        if message_type == "text":
            text = message.get("text", {}).get("body")

        # ----------------------------------------------------
        # 4. Mensaje interactivo (botones o lista)
        # ----------------------------------------------------
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                button_id = interactive.get("button_reply", {}).get("id")

            elif interactive_type == "list_reply":
                button_id = interactive.get("list_reply", {}).get("id")

        # ----------------------------------------------------
        # 5. Ignorar otros tipos (image, document, etc.)
        # ----------------------------------------------------
        else:
            return None

        return {
            "phone": phone,
            "text": text,
            "button_id": button_id,
            "is_status": False,
        }

    except Exception:
        # Nunca romper el webhook por error de parsing
        return None
