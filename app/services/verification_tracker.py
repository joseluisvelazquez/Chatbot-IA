# app/services/verification_tracker.py

from app.core.states import ChatState
from app.services.verification_service import VerificationService


STEP_MAP = {
    ChatState.CONFIRMAR_FOLIO: "folio",
    ChatState.CONFIRMAR_NOMBRE: "nombre",
    ChatState.CONFIRMAR_DOMICILIO: "domicilio",
    ChatState.CONFIRMAR_FECHA: "fecha",
    ChatState.CONFIRMAR_PRODUCTO: "producto",
    ChatState.CONFIRMAR_COMPONENTES: "componentes",
    ChatState.CONFIRMAR_PAGO_INICIAL: "pagoInicial",
    ChatState.INFO_PAGOS: "pagos",
    ChatState.INFO_PLAN_3_MESES: "plan3meses",
    ChatState.INFO_OTROS_PLANES: "planes",
    ChatState.INFO_METODOS_PAGO: "bancos",
    ChatState.INFO_BENEFICIOS: "beneficios",
    ChatState.FINALIZADO: "finalizado",
}


NEGATIVE_INTENTS = {
    "FOLIO_NO",
    "NOMBRE_NO",
    "DOMICILIO_NO",
    "FECHA_NO",
    "PROD_NO",
    "PAGO_NO",
    "COMP_NO",
    "PAGOS_DUDA",
    "PLAN3_DUDA",
    "PLAN_DUDA",
    "METODOS_DUDA",
    "BEN_DUDA",
}


def track_verification(
    db,
    session,
    current_state,
    detected_intent,
    next_state,
):
    """
    Guarda el progreso de verificación.

    0 = no respondido
    1 = respuesta afirmativa
    2 = respuesta negativa
    """

    if db is None:
        return

    folio = getattr(session, "folio", None)
    if not folio:
        return

    step = STEP_MAP.get(current_state)

    if not step:
        return

    value = None

    if detected_intent in NEGATIVE_INTENTS:
        value = 2

    else:
        value = 1

    VerificationService(db).mark_step_from_folio(
        str(folio),
        step,
        value=value
    )