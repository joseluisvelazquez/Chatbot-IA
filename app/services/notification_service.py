"""
Servicio de notificaciones a asesores por WhatsApp.

Envía alertas breves a los números configurados en ADVISOR_PHONES
cada vez que una sesión entra en un estado que requiere atención humana.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.adapters.whatsapp_client import send_whatsapp_message
from app.config.settings import settings
from app.core.states.states import ChatState
from app.db.models import ChatSessions

logger = logging.getLogger(__name__)

# Estados que representan que el caso ya está en atención humana.
# Si la sesión ya estaba en uno de estos, no re-notificamos.
_ATTENTION_STATES = {ChatState.ACLARACION.value, ChatState.LLAMADA.value}


async def notify_advisors_new_case(
    session: ChatSessions,
    reason: str,
    no_cuenta: Optional[str] = None,
) -> None:
    """
    Envía un mensaje breve a cada asesor configurado en ADVISOR_PHONES.
    """
    phones: list[str] = settings.ADVISOR_PHONES
    if not phones:
        return

    folio_val = session.folio or "No asignado"
    cuenta_val = no_cuenta or "No asignada"

    message = (
        f"🚨 *Nuevo caso que requiere atención*\n\n"
        f"Folio: {folio_val}\n"
        f"Número de cuenta: {cuenta_val}\n"
        f"Motivo: {reason}\n\n"
        f"Revisa el panel de verificaciones."
    )

    for advisor_phone in phones:
        try:
            await send_whatsapp_message(advisor_phone, text=message)
            logger.info(
                "advisor_notification_sent",
                extra={"advisor_phone_last4": advisor_phone[-4:]},
            )
        except Exception:
            logger.exception(
                "advisor_notification_failed",
                extra={"advisor_phone_last4": advisor_phone[-4:]},
            )


async def notify_if_attention_needed(
    session: ChatSessions,
    old_state: Optional[str],
    new_state: str,
    no_cuenta: Optional[str] = None,
) -> None:
    """
    Evalúa si un cambio de estado amerita notificar a los asesores.
    Solo notifica en la *transición* hacia un estado de atención,
    no si ya estábamos en uno.
    """
    # Si ya estaba en un estado de atención, no volver a notificar
    if old_state in _ATTENTION_STATES:
        return

    if new_state == ChatState.LLAMADA.value:
        # Caso 1: Llamada solicitada activamente
        reason = "El cliente solicitó hablar con un asesor por llamada."
        await notify_advisors_new_case(session, reason, no_cuenta=no_cuenta)
        
    elif new_state == ChatState.ACLARACION.value:
        # Caso 2 y 3: Inconsistencias o Dudas
        from app.core.states.state_types import get_state_type
        
        reason = "Se detectó una inconsistencia crítica que detuvo la verificación."
        if old_state:
            try:
                from app.core.states.states import ChatState as CS
                if get_state_type(CS(old_state)) == "information":
                    reason = "El cliente tiene dudas que la IA no pudo resolver."
            except ValueError:
                pass
                
        await notify_advisors_new_case(session, reason, no_cuenta=no_cuenta)
