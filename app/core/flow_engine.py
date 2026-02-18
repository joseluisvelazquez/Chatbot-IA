from app.core.flow import FLOW, DEFAULT_TRANSITIONS
from app.core.states import ChatState
from app.core.intents import detect_intent

INTERRUPT_STATES = {
    ChatState.ACLARACION,
    ChatState.INCONSISTENCIA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.LLAMADA,
}

def process_message(session, text: str, intent: str = None):

    text = text or ""

    current_state = ChatState(session.state)
    flow = FLOW.get(current_state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, [], None

    # Default seguro
    next_state = current_state

    # Prioridad botón
    if intent:
        detected_intent = intent
    else:
        detected_intent = detect_intent(text, current_state)
    
    # Bloqueo de arranque
    if current_state == ChatState.INICIO and detected_intent != "start_verification" and not intent:
        return "", current_state, [], None

    # Ambiguo binario
    if detected_intent == "ambiguous":
        return (
            "Solo necesito que confirmes con 'Sí' o 'No'.",
            current_state,
            flow.get("buttons", []),
            None,
        )

    options = flow.get("options", {})

    # Transición específica
    if detected_intent in options:
        next_state = options[detected_intent]

    # Transición global
    elif detected_intent in DEFAULT_TRANSITIONS:
        next_state = DEFAULT_TRANSITIONS[detected_intent]

    # Fallback → repetir estado
    else:
        next_state = current_state

    previous_state_to_save = None

    if next_state in INTERRUPT_STATES:
        previous_state_to_save = session.state

    if next_state == "__RESUME__":
        next_state = (
            ChatState(session.previous_state)
            if session.previous_state
            else ChatState.INICIO
        )

    next_flow = FLOW.get(next_state, {})

    formatted_text = next_flow.get("text", "")

    return (
        formatted_text,
        next_state,
        next_flow.get("buttons", []),
        previous_state_to_save,
    )
