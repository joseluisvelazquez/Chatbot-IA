from app.core.states.states import ChatState
from app.core.flow.flow import FLOW


def resolve_next_state(current_state, action, detected_intent=None, previous_state=None):
    """
    Determina el siguiente estado basado en:
    - estado actual
    - acción (intent_router)
    """

    # --------------------------------------
    # RESUME DESDE BOTÓN (__RESUME__)
    # --------------------------------------
    if detected_intent == "__RESUME__":
        return ChatState(previous_state) if previous_state else ChatState.INICIO

    # --------------------------------------
    # REANUDAR FLUJO
    # --------------------------------------
    if action == "resume":
        return ChatState(previous_state) if previous_state else ChatState.INICIO

    # --------------------------------------
    # AVANZAR EN EL FLUJO (botones)
    # --------------------------------------
    if action == "advance":

        state_config = FLOW.get(current_state)

        if not state_config:
            return None

        options = state_config.get("options", {})

        if detected_intent in options:
            return options[detected_intent]

        if detected_intent == "REANUDACION":
            return current_state

        return current_state

    # --------------------------------------
    # REPETIR ESTADO SIN AVANZAR
    # --------------------------------------
    if action == "repeat":
        return current_state

    # --------------------------------------
    # INCONSISTENCIA
    # --------------------------------------
    if action == "inconsistency":
        return ChatState.INCONSISTENCIA

    # --------------------------------------
    # PAUSA
    # --------------------------------------
    if action == "pause":
        return ChatState.RECORDATORIO

    # --------------------------------------
    # ESCALAMIENTO HUMANO (CHAT)
    # --------------------------------------
    if action == "escalate":
        return ChatState.LLAMADA

    # --------------------------------------
    # ESCALAMIENTO LLAMADA
    # --------------------------------------
    if action == "escalate_call":
        return ChatState.LLAMADA

    # --------------------------------------
    # IA (fallback)
    # --------------------------------------
    if action == "ai":
        return current_state

    # --------------------------------------
    # INICIO
    # --------------------------------------
    if action == "start":
        return ChatState.INICIO

    return current_state
