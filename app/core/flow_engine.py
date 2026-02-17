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


def process_message(state, text: str, intent: str = None, previous_state: str | None = None):

    current_state = ChatState(state)
    flow = FLOW.get(current_state)

    if not flow:
        return "Un asesor te contactará.", ChatState.LLAMADA, [], None, None

    # 1️⃣ Botón tiene prioridad
    detected_intent = intent if intent else detect_intent(text, current_state)

    # 2️⃣ Ambiguo en binario
    if detected_intent == "ambiguous":
        return (
            "Solo necesito que confirmes con 'Sí' o 'No'.",
            current_state,
            flow.get("buttons", []),
            None,
            None,
        )

    # 3️⃣ Opciones específicas del estado
    next_state = None

    if detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]

        if next_state == "__RESUME__":
            next_state = ChatState(previous_state) if previous_state else ChatState.INICIO

    # 4️⃣ Transiciones globales
    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other":
        next_state = DEFAULT_TRANSITIONS[detected_intent]

    # 5️⃣ FUERA DE FLUJO → IA
    else:
        ai_result = handle_out_of_flow(current_state, text)

        if ai_result and ai_result.get("action") == "respond":
            return (
                ai_result["reply"],
                current_state,
                flow.get("buttons", []),
                None,
                None,
            )

        next_state = ChatState.FUERA_DE_FLUJO

    # Guardar estado previo si es interrupción
    previous_state_to_save = None
    if next_state in INTERRUPT_STATES:
        previous_state_to_save = current_state.value

    next_flow = FLOW.get(next_state, {})

    document = next_flow.get("document")  # 👈 soporte documentos

    return (
        next_flow.get("text", ""),
        next_state,
        next_flow.get("buttons", []),
        previous_state_to_save,
        document,
    )
