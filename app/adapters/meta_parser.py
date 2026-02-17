def build_meta_buttons(buttons: list):
    return [
        {
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["label"],  # Meta límite 20 chars
            },
        }
        for b in buttons[:3]  # Meta máximo 3 botones
    ]
