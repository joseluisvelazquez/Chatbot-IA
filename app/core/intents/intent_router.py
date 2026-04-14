from app.core.states.state_types import get_state_type


def route_intent(state, intent):
    """
    Decide la acción que debe ejecutar el flow_engine
    según:
    - estado actual
    - intención detectada
    """

    state_type = get_state_type(state)

    # =================================================
    # NORMALIZACIÓN GLOBAL (ANTES DE TODO)
    # =================================================

    # saludo → respuesta estática (se maneja en flow_engine)
    if intent == "greeting":
        return "greeting"

    # posponer
    if intent == "later":
        return "pause"

    # llamada directa
    if intent == "call":
        return "escalate_call"

    # humano (chat)
    if intent == "human":
        return "escalate"

    # IA (separada por tipo)
    if intent == "doubt":
        return "ai_doubt"

    if intent == "ambiguous":
        return "ai_ambiguous"

    if intent == "other":
        return "ai_out"

    # =================================================
    # CONFIRMATION STATES
    # =================================================

    if state_type == "confirmation":

        if intent == "affirmative":
            return "advance"

        if intent == "negative":
            return "advance"

        # cualquier otra cosa → IA
        return "ai"

    # =================================================
    # INFORMATION STATES
    # =================================================

    if state_type == "information":

        if intent == "affirmative":
            return "advance"

        # dudas o texto → IA
        return "ai"

    # =================================================
    # SELECTION STATES
    # =================================================

    if state_type == "selection":

        if intent in ("affirmative", "negative"):
            return "advance"

        return "ai"

    # =================================================
    # INCONSISTENCY STATES
    # =================================================

    if state_type == "inconsistency":

        # continuar flujo
        if intent == "affirmative":
            return "resume"

        # todo lo demás → IA (para analizar inconsistencia)
        return "ai"

    # =================================================
    # AI STATES (DUDA / FUERA_DE_FLUJO)
    # =================================================

    if state_type == "ai":
        return "ai"

    # =================================================
    # HUMAN STATES (ACLARACION / LLAMADA)
    # =================================================

    if state_type == "human":

        if intent == "affirmative":
            return "resume"

        return "ignore"

    # =================================================
    # SYSTEM STATES
    # =================================================

    if state_type == "system":

        if intent == "start_verification":
            return "start"
            
        if intent == "affirmative":
            return "advance"

        return "ignore"

    # =================================================
    # FALLBACK GLOBAL
    # =================================================

    return "ai"