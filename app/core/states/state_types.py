from app.core.states.states import ChatState

# ---------------------------------------------------------
# Estados de confirmación
# ---------------------------------------------------------
# Si usuario dice NO → INCONSISTENCIA

STATE_CONFIRMATION = {
    ChatState.INICIO,
    ChatState.INICIO2,
    ChatState.CONFIRMAR_NOMBRE,
    ChatState.CONFIRMAR_DOMICILIO,
    ChatState.CONFIRMAR_FECHA,
    ChatState.CONFIRMAR_PRODUCTO,
    ChatState.CONFIRMAR_ESTADO_PRODUCTO,
    ChatState.CONFIRMAR_COMPONENTES,
    ChatState.CONFIRMAR_PAGO_INICIAL,
}


# ---------------------------------------------------------
# Estados informativos
# ---------------------------------------------------------
# Si usuario tiene duda → DUDA

STATE_INFORMATION = {
    ChatState.INFO_PAGOS,
    ChatState.INFO_METODOS_PAGO,
    ChatState.INFO_COMPROBANTE_ACCESO,
    ChatState.INFO_PLAN_3_MESES,
    ChatState.INFO_OTROS_PLANES,
    ChatState.INFO_BENEFICIOS,
    ChatState.INFO_BENEFICIOS2,
}


# ---------------------------------------------------------
# Estados de acuse simple
# ---------------------------------------------------------
# No generan dudas, inconsistencias ni IA.

STATE_ACKNOWLEDGEMENT = {
}


# ---------------------------------------------------------
# Estados de selección
# ---------------------------------------------------------

STATE_SELECTION = {
    ChatState.COMPONENTES_FALTANTES,
    ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
    ChatState.MENU_AYUDA,
}


# ---------------------------------------------------------
# Estados de inconsistencia
# ---------------------------------------------------------

STATE_INCONSISTENCY = {
    ChatState.INCONSISTENCIA,
}


# ---------------------------------------------------------
# Estados manejados por IA
# ---------------------------------------------------------

STATE_AI = {
    ChatState.FUERA_DE_FLUJO,
    ChatState.DUDA,
}


# ---------------------------------------------------------
# Estados de atención humana
# ---------------------------------------------------------

STATE_HUMAN = {
    ChatState.ACLARACION,
    ChatState.LLAMADA,
}


# ---------------------------------------------------------
# Estados del sistema
# ---------------------------------------------------------

STATE_SYSTEM = {
    ChatState.ESPERA,
    ChatState.RECORDATORIO_1H,
    ChatState.RECORDATORIO_2H,
    ChatState.RECORDATORIO,
    ChatState.FINALIZADO,
    ChatState.DESPEDIDA,
    ChatState.COBRANZA,
    ChatState.COBRANZA_DUDA,
    ChatState.COBRANZA_ESCALADO,
}


# ---------------------------------------------------------
# Helper
# ---------------------------------------------------------

def get_state_type(state: ChatState) -> str:
    if state in STATE_CONFIRMATION:
        return "confirmation"

    if state in STATE_INFORMATION:
        return "information"

    if state in STATE_ACKNOWLEDGEMENT:
        return "acknowledgement"

    if state in STATE_SELECTION:
        return "selection"

    if state in STATE_INCONSISTENCY:
        return "inconsistency"

    if state in STATE_AI:
        return "ai"

    if state in STATE_HUMAN:
        return "human"

    if state in STATE_SYSTEM:
        return "system"

    return "unknown"

def is_persistent_state(state: ChatState) -> bool:
    """
    Retorna True si el estado es un estado "principal" del flujo de verificación
    del cual el usuario NO debería ser redirigido accidentalmente al salir de un
    estado de servicio (ej. MENU_AYUDA, DUDA).
    """
    return get_state_type(state) in ("confirmation", "information", "acknowledgement") or is_terminal_state(state)

def is_terminal_state(state: ChatState) -> bool:
    """
    Retorna True si el estado marca el final completo del proceso (ej. finalización,
    escalamiento definitivo a llamada).
    """
    return state in {
        ChatState.FINALIZADO,
        ChatState.DESPEDIDA,
        ChatState.ACLARACION,
        ChatState.LLAMADA,
        ChatState.DEVOLUCION_FINALIZADA,
        ChatState.COBRANZA,
        ChatState.COBRANZA_DUDA,
        ChatState.COBRANZA_ESCALADO
    }

TERMINAL_STATES_FOR_LOCK = {
    ChatState.FINALIZADO,
    ChatState.DESPEDIDA,
    ChatState.COBRANZA,
    ChatState.COBRANZA_DUDA,
    ChatState.COBRANZA_ESCALADO,
    ChatState.ACLARACION,
    ChatState.LLAMADA,
    ChatState.DEVOLUCION_FINALIZADA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.ESPERA,
}

def get_menu_ayuda_buttons(previous_state: str) -> list:
    """
    Retorna los botones del menú de ayuda, excluyendo la opción de "Ir a verificación"
    si ya se alcanzó un estado terminal.
    """
    from app.core.flow.flow import FLOW
    
    buttons = FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", []).copy()
    
    try:
        if previous_state and is_terminal_state(ChatState(previous_state)):
            buttons = [b for b in buttons if b.get("id") != "MENU_VERIFICACION"]
    except ValueError:
        pass
        
    return buttons
