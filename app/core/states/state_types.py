from app.core.states.states import ChatState

# ---------------------------------------------------------
# Estados de confirmación
# ---------------------------------------------------------
# Si usuario dice NO → INCONSISTENCIA

STATE_CONFIRMATION = {
    ChatState.CONFIRMAR_FOLIO,
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
    ChatState.INFO_PLAN_3_MESES,
    ChatState.INFO_OTROS_PLANES,
    ChatState.INFO_BENEFICIOS,
    ChatState.INFO_BENEFICIOS2,
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
    ChatState.INICIO,
    ChatState.RECORDATORIO_1H,
    ChatState.RECORDATORIO_2H,
    ChatState.RECORDATORIO,
    ChatState.FINALIZADO,
}


# ---------------------------------------------------------
# Helper
# ---------------------------------------------------------

def get_state_type(state: ChatState) -> str:
    if state in STATE_CONFIRMATION:
        return "confirmation"

    if state in STATE_INFORMATION:
        return "information"

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