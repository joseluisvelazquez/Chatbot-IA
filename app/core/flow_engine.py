from app.core.flow import FLOW, DEFAULT_TRANSITIONS
from app.core.states import ChatState
from app.core.intents import detect_intent
from app.services.ai_module import handle_out_of_flow
from dataclasses import dataclass
from app.core.states import ChatState
from app.utils.restart_detector import wants_restart
# Estados que requieren guardar el estado previo para poder reanudar después de la interrupción
INTERRUPT_STATES = {
    ChatState.ACLARACION,
    ChatState.INCONSISTENCIA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.LLAMADA,
}

@dataclass
class FlowResult:
    reply: str
    next_state: ChatState
    buttons: list
    previous_state: str | None = None

def process_message(session, text: str, intent: str | None = None) -> FlowResult:

    current_state = ChatState(session.state)
    previous_state = session.previous_state

    flow = FLOW.get(current_state)

    if not flow:
        return FlowResult(
            "Un asesor te contactará.",
            ChatState.LLAMADA,
            []
        )

    # ------------------------------------------------
    # RESTART GLOBAL
    # ------------------------------------------------
    if wants_restart(text):
        next_state = ChatState.INICIO
        flow = FLOW[next_state]

        return FlowResult(
            "Perfecto 👍 reiniciemos tu proceso.\n\n" + flow["text"],
            next_state,
            flow.get("buttons", []),
            None
        )

    # ------------------------------------------------
    # REANUDAR DESPUÉS DE ESPERA
    # ------------------------------------------------
    if current_state == ChatState.ESPERA:
        next_state = ChatState.INICIO
        flow = FLOW[next_state]

        return FlowResult(
            flow["text"],
            next_state,
            flow.get("buttons", []),
            None
        )

    # ------------------------------------------------
    # INTENT DETECTION
    # ------------------------------------------------
    detected_intent = intent if intent else detect_intent(text, current_state)

    if detected_intent == "ambiguous":
        return FlowResult(
            "Por favor responde Sí o No.",
            current_state,
            flow.get("buttons", []),
            None
        )

    # ------------------------------------------------
    # OPCIONES DEL ESTADO
    # ------------------------------------------------
    next_state = None

    if detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]

        if next_state == "__RESUME__":
            next_state = ChatState(previous_state) if previous_state else ChatState.INICIO

    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other":
        next_state = DEFAULT_TRANSITIONS[detected_intent]

    else:
        ai_result = handle_out_of_flow(current_state, text)

        if ai_result and ai_result.get("action") == "respond":
            return FlowResult(
                ai_result["reply"],
                current_state,
                flow.get("buttons", []),
                None
            )

        next_state = ChatState.FUERA_DE_FLUJO

    # guardar estado previo
    previous_state_to_save = None
    if next_state in INTERRUPT_STATES:
        previous_state_to_save = current_state.value

    next_flow = FLOW.get(next_state, {})

    return FlowResult(
        next_flow.get("text", ""),
        next_state,
        next_flow.get("buttons", []),
        previous_state_to_save
    )
