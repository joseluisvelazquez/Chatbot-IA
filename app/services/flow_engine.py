from app.core.flow import FLOW
from app.core.states import ChatState

def process_message(state: ChatState, text: str = None, button_id: str = None):
    flow = FLOW.get(state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, []

    # Botón presionado
    if button_id and button_id in flow["options"]:
        next_state = flow["options"][button_id]
        next_flow = FLOW.get(next_state, {})
        return (
            next_flow.get("text", ""),
            next_state,
            next_flow.get("buttons", []),
        )

    # Texto libre → IA / aclaración
    if text:
        return (
            "Déjame ayudarte con tu duda 😊",
            ChatState.ACLARACION,
            [],
        )

    # Caso inválido
    return (
        "Por favor selecciona una opción válida.",
        state,
        flow.get("buttons", []),
    )
