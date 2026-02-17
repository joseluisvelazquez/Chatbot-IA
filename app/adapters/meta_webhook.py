def parse_meta_message(payload: dict):
    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]

        return {
            "phone": message["from"],
            "text": message.get("text", {}).get("body", ""),
            "message_id": message["id"],
            "button_id": message.get("interactive", {})
            .get("button_reply", {})
            .get("id"),
        }

    except (KeyError, IndexError):
        return None
