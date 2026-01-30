from app.core.flow import FLOW
from app.core.states import ChatState

def process_message(state: ChatState, text: str = None, button_id: str = None):
    flow = FLOW.get(state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, []

    # 🟢 Botón válido
    if button_id and button_id in flow["options"]:
        next_state = flow["options"][button_id]
        next_flow = FLOW.get(next_state, {})
        return (
            next_flow.get("text", ""),
            next_state,
            next_flow.get("buttons", []),
        )

    # 🟡 Texto libre → ACLARACIÓN
    if text:
        aclaracion_flow = FLOW[ChatState.ACLARACION]
        return (
            aclaracion_flow["text"],
            ChatState.ACLARACION,
            aclaracion_flow["buttons"],
        )

    # 🔴 Caso inválido (ni texto ni botón válido)
    return (
        "Por favor selecciona una opción válida.",
        state,
        flow.get("buttons", []),
    )
