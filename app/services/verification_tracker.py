import logging

from app.core.states.states import ChatState
from app.services.verification_service import VerificationService, VerificationTransitionError

logger = logging.getLogger(__name__)


STEP_MAP = {
    ChatState.CONFIRMAR_FOLIO: "folio",
    ChatState.CONFIRMAR_NOMBRE: "nombre",
    ChatState.CONFIRMAR_DOMICILIO: "domicilio",
    ChatState.CONFIRMAR_FECHA: "fecha",
    ChatState.CONFIRMAR_PRODUCTO: "producto",

    ChatState.CONFIRMAR_COMPONENTES: "componentes",
    ChatState.CONFIRMAR_ESTADO_PRODUCTO: "componentes",

    ChatState.CONFIRMAR_PAGO_INICIAL: "pagoInicial",
    ChatState.INFO_PAGOS: "pagos",
    ChatState.INFO_PLAN_3_MESES: "plan3meses",
    ChatState.INFO_OTROS_PLANES: "planes",
    ChatState.INFO_METODOS_PAGO: "bancos",

    ChatState.INFO_BENEFICIOS: "beneficios",
    ChatState.INFO_BENEFICIOS2: "beneficios",
    
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
    "PROD_ESTADO_NO"
    
}
DOUBT_INTENTS = {
    "doubt",
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
):
    """
    Guarda el progreso de verificación.

    0 = no respondido
    1 = respuesta afirmativa
    2 = respuesta negativa / inconsistencia detectada (solo aplica para algunos pasos)
    3 = duda 
    """

    print(f"DEBUG: track_verification called with current_state={current_state}, detected_intent={detected_intent}")


    if db is None:
        return

    folio = getattr(session, "folio", None)
    print(f"DEBUG: Tracking verification for folio {folio}")

    if not folio:
        return

    step = STEP_MAP.get(current_state)

    print(f"DEBUG: Mapped current_state {current_state} to step {step}")

    if not step:
        return

    value = 1  # por defecto, asumimos que cualquier respuesta que no sea negativa o de duda es afirmativa

    if detected_intent in NEGATIVE_INTENTS:
        value = 2

    elif detected_intent in DOUBT_INTENTS:
        value = 3
    

    try:
        VerificationService(db).mark_step_from_folio(
            str(folio),
            step,
            value=value,
            phone=session.phone,
            event_id=getattr(session, "last_message_id", None),
        )
    except VerificationTransitionError as exc:
        logger.warning(
            "verification_transition_rejected",
            extra={
                "session_id": getattr(session, "id", None),
                "phone": getattr(session, "phone", None),
                "folio": folio,
                "step": step,
                "value": value,
                "reason": str(exc),
            },
        )
