import logging

from app.core.states.states import ChatState
from app.core.verification.verification_schema import VERIFICATION_STEP_ORDER
from app.services.verification_service import VerificationService, VerificationTransitionError
from app.services.siga_bridge_sale import bridge_sale_from_payload, bridge_sale_from_session, bridge_verification_found

logger = logging.getLogger(__name__)


def _mask(value, *, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


STEP_MAP = {
    ChatState.INICIO:                "nombre",
    ChatState.INICIO2:               "nombre",
    ChatState.CONFIRMAR_NOMBRE:      "nombre",
    ChatState.CONFIRMAR_DOMICILIO:   "domicilio",
    ChatState.CONFIRMAR_FECHA:       "fecha",
    ChatState.CONFIRMAR_PRODUCTO:    "producto",

    ChatState.CONFIRMAR_COMPONENTES:      "componentes",
    ChatState.CONFIRMAR_ESTADO_PRODUCTO:  "componentes",

    ChatState.CONFIRMAR_PAGO_INICIAL: "pagoInicial",
    ChatState.INFO_PAGOS:             "pagos",
    ChatState.INFO_PLAN_3_MESES:      "plan3meses",
    ChatState.INFO_OTROS_PLANES:      "planes",
    ChatState.INFO_METODOS_PAGO:      "bancos",
    ChatState.INFO_COMPROBANTE_ACCESO: "comprobanteAcceso",

    ChatState.INFO_BENEFICIOS:  "beneficios",
    ChatState.INFO_BENEFICIOS2: "beneficios",

    # ChatState.FINALIZADO: "finalizado",
}

# Etiquetas legibles para mostrar en el panel (columna "Estado actual").
# Separado de STEP_MAP para no afectar la validación interna de pasos.
STEP_DISPLAY_LABELS: dict[str, str] = {
    "nombre":      "Nombre",
    "domicilio":   "Domicilio",
    "fecha":       "Fecha venta",
    "producto":    "Producto",
    "componentes": "Componentes",
    "pagoInicial": "Pago inicial",
    "pagos":       "Pagos",
    "plan3meses":  "Plan 3 meses",
    "planes":      "Otros planes",
    "bancos":      "Métodos de pago",
    "comprobanteAcceso": "Datos de acceso para comprobante",
    "beneficios":  "Beneficios",
    "finalizado":  "Finalizado",
    "inicio":      "Inicio",
    "folio":       "Folio",
}



NEGATIVE_INTENTS = {
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


def _mark_bridge_step_with_backfill(
    service: VerificationService,
    *,
    no_cuenta: str,
    step: str,
    value: int,
    phone: str,
    event_id: str | None,
) -> None:
    if step not in VERIFICATION_STEP_ORDER:
        service.update_step_atomic(
            no_cuenta=no_cuenta,
            step=step,
            value=value,
            phone=phone,
            event_id=event_id,
        )
        return

    step_index = VERIFICATION_STEP_ORDER.index(step)
    for previous_step in VERIFICATION_STEP_ORDER[:step_index]:
        try:
            service.update_step_atomic(
                no_cuenta=no_cuenta,
                step=previous_step,
                value=1,
                phone=phone,
                event_id=event_id,
            )
        except VerificationTransitionError:
            # Si ya estaba marcado como inconsistencia (2) o duda (3), no lo pisamos.
            continue

    service.update_step_atomic(
        no_cuenta=no_cuenta,
        step=step,
        value=value,
        phone=phone,
        event_id=event_id,
    )


def track_verification(
    db,
    session,
    current_state,
    detected_intent,
    bridge_verification=None,
):
    """
    Guarda el progreso de verificación.

    0 = no respondido
    1 = respuesta afirmativa
    2 = respuesta negativa / inconsistencia detectada (solo aplica para algunos pasos)
    3 = duda 
    """

    if db is None:
        return

    folio = getattr(session, "folio", None)

    if not folio:
        return

    step = STEP_MAP.get(current_state)

    if not step:
        return

    value = 1  # por defecto, asumimos que cualquier respuesta que no sea negativa o de duda es afirmativa

    if detected_intent in NEGATIVE_INTENTS:
        value = 2

    elif detected_intent in DOUBT_INTENTS:
        value = 3
    

    try:
        service = VerificationService(db)
        try:
            result = service.mark_step_from_folio(
                str(folio),
                step,
                value=value,
                phone=session.phone,
                event_id=getattr(session, "last_message_id", None),
            )
        except VerificationTransitionError:
            no_cuenta = service.resolve_no_cuenta_from_folio(str(folio))
            if no_cuenta:
                _mark_bridge_step_with_backfill(
                    service,
                    no_cuenta=str(no_cuenta),
                    step=step,
                    value=value,
                    phone=session.phone,
                    event_id=getattr(session, "last_message_id", None),
                )
                return
            raise

        if result is not None:
            return

        bridge_payload = bridge_verification if bridge_verification_found(bridge_verification) else None
        bridge_sale = (
            bridge_sale_from_payload(bridge_payload)
            or bridge_sale_from_session(session, str(folio))
        )
        no_cuenta = getattr(bridge_sale, "no_cuenta", None) if bridge_sale else None
        if no_cuenta:
            _mark_bridge_step_with_backfill(
                service,
                no_cuenta=str(no_cuenta),
                step=step,
                value=value,
                phone=session.phone,
                event_id=getattr(session, "last_message_id", None),
            )
    except VerificationTransitionError as exc:
        logger.warning(
            "verification_transition_rejected",
            extra={
                "session_id": getattr(session, "id", None),
                "phone_last4": _mask(getattr(session, "phone", None)),
                "folio_masked": _mask(folio),
                "step": step,
                "value": value,
                "reason": str(exc),
            },
        )
