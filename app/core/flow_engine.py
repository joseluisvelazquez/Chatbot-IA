from app.core.flow import FLOW, DEFAULT_TRANSITIONS
from app.core.states import ChatState
from app.core.intents import detect_intent
from app.services.ai_module import handle_out_of_flow

INTERRUPT_STATES = {
    ChatState.ACLARACION,
    ChatState.INCONSISTENCIA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.LLAMADA,
}


def process_message(session, text: str, intent: str = None):

    current_state = ChatState(session.state)
    flow = FLOW.get(current_state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, [], None

    # 1️⃣ Botón tiene prioridad
    if intent:
        detected_intent = intent
    else:
        detected_intent = detect_intent(text, current_state)

    # 2️⃣ Ambiguo en binario
    if detected_intent == "ambiguous":
        return (
            "Solo necesito que confirmes con 'Sí' o 'No'.",
            current_state,
            flow.get("buttons", []),
            None,
        )

    # 3️⃣ Opciones específicas del estado
    if detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]

    # 4️⃣ Transiciones globales
    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other":
        next_state = DEFAULT_TRANSITIONS[detected_intent]


    # 5️⃣ FUERA DE FLUJO → IA


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

    return (
        next_flow.get("text", ""),
        next_state,
        next_flow.get("buttons", []),
        previous_state_to_save,
    )
