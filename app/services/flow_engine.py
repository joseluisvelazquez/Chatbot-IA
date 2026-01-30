from app.core.flow import FLOW
from app.core.states import ChatState

def process_message(state: ChatState, text: str = None, button_id: str = None):
    flow = FLOW.get(state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, []

    # 1️⃣ ENTRADA AL ESTADO (sin botón y sin texto)
    if button_id is None and text is None:
        # Auto avance (caso ESPERA → INICIO)
        if "auto_next" in flow:
            next_state = flow["auto_next"]
            next_flow = FLOW.get(next_state)
            return (
                flow["text"],
                next_state,
                next_flow.get("buttons", []),
            )

        # Render normal del estado
        return (
            flow["text"],
            state,
            flow.get("buttons", []),
        )

    # 2️⃣ BOTÓN PRESIONADO (válido)
    if button_id and button_id in flow.get("options", {}):
        next_state = flow["options"][button_id]
        next_flow = FLOW.get(next_state, {})
        return (
            next_flow.get("text", ""),
            next_state,
            next_flow.get("buttons", []),
        )

    # 3️⃣ TEXTO LIBRE → IA / ACLARACIÓN
    if text:
        return (
            "Déjame ayudarte con tu duda 😊",
            ChatState.ACLARACION,
            [],
        )

    # 4️⃣ BOTÓN INVÁLIDO
    return (
        "Por favor selecciona una opción válida.",
        state,
        flow.get("buttons", []),
    )
