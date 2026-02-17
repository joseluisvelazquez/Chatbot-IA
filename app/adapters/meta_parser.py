def build_meta_buttons(buttons: list): # Convierte la lista de botones del flujo a formato Meta
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
