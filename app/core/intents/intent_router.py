from app.core.states.state_types import get_state_type


def route_intent(state, intent):
    """
    Decide la acción que debe ejecutar el flow_engine
    según:
    - estado actual
    - intención detectada
    """

    state_type = get_state_type(state)

    if state_type == "acknowledgement":

        if intent == "COMPROBANTE_ACCESO_OK":
            return "advance"

        return "repeat"

    # =================================================
    # NORMALIZACIÓN GLOBAL (ANTES DE TODO)
    # =================================================

    # Si estamos en atención humana (o en fase de cobranza/finalizada), el bot no interfiere.
    # Excepción: "resume" o "start" para reiniciar flujos.
    if state_type == "human" or state in ("finalizado", "despedida", "cobranza"):
        if intent in ("affirmative", "resume"):
            return "resume"
        if intent == "start_verification":
            return "start"
        return "ignore"

    if intent == "resume":
        state_val = state.value if hasattr(state, "value") else state
        if state_type in ("system", "ai") or state_val in ("menu_ayuda", "menu_duda"):
            return "resume"
        # Repite el estado actual (re-envía la pregunta/mensaje donde se quedó atorado)
        return "repeat"

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
    # SYSTEM STATES
    # =================================================

    if state_type == "system":

        if intent == "start_verification":
            return "start"
            
        if intent in ("affirmative", "negative", "thanks"):
            return "advance"

        return "ignore"

    # =================================================
    # FALLBACK GLOBAL
    # =================================================

    return "ai"
