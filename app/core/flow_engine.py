from __future__ import annotations

from app.content.message_builder import MessageBuilder
from app.core.flow import FLOW, DEFAULT_TRANSITIONS
from app.core.states import ChatState
from app.core.intents import detect_intent
from app.services.ai_module import handle_out_of_flow
from app.core.states import ChatState
from dataclasses import dataclass
from app.utils.restart_detector import wants_restart
from app.siga.siga_repository import (
    obtener_venta_por_folio,
    obtener_domicilio_por_movimiento,
    construir_nombre,
    construir_producto,
    construir_no_cuenta,
)
from app.utils import address_formatter

from app.content.message_builder import MessageBuilder
from app.content import messages
from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
from app.utils.date_formatter import formatear_fecha_larga
from app.config.settings import settings

@dataclass
class FlowResult:
    reply: str
    next_state: ChatState
    buttons: list
    previous_state: str | None = None
    image_id: str | None = None


def process_message(
    session, text: str, intent: str | None = None, db=None
) -> FlowResult:

    current_state = ChatState(session.state)
    previous_state = session.previous_state
    flow = FLOW.get(current_state)

    if not flow:
        return FlowResult("Un asesor te contactará.", ChatState.LLAMADA, [])

    # --------------------------------------
    # Detectar intención
    # --------------------------------------
    if intent:
        detected_intent = intent
        folio = None
    else:
        detected_intent, folio = detect_intent(text, current_state)
    # --------------------------------------
    # Si mandó folio para iniciar
    # --------------------------------------
    if detected_intent == "start_verification":

        venta = obtener_venta_por_folio(db, folio)

        if not venta:
            return FlowResult(
                "❌ No encontramos tu folio. Verifica e intenta nuevamente.",
                current_state,
                flow.get("buttons", []),
            )

        # Guardamos folio en sesión
        session.folio = folio

        # Pasamos directo a confirmar nombre
        next_state = ChatState.CONFIRMAR_FOLIO

    # --------------------------------------
    # Cambio manual de folio
    # --------------------------------------
    elif current_state == ChatState.CAMBIAR_FOLIO:

        nuevo_folio = text.strip()

        venta = obtener_venta_por_folio(db, nuevo_folio)

        if not venta:
            return FlowResult(
                "❌ Ese folio no existe. Intenta nuevamente.",
                current_state,
                [],
                previous_state,
            )

        # Reemplazamos el folio
        session.folio = nuevo_folio

        next_state = ChatState.CONFIRMAR_FOLIO
        
    # --------------------------------------
    # Transiciones normales
    # --------------------------------------
    elif detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]

        # Guardar estado anterior si vamos a inconsistencia o similares
        if next_state in [
            ChatState.INCONSISTENCIA,
            ChatState.FUERA_DE_FLUJO,
            ChatState.ACLARACION,
            ChatState.LLAMADA,
        ]:
            previous_state = session.state

        if next_state == "__RESUME__":
            next_state = (
                ChatState(previous_state) if previous_state else ChatState.INICIO
            )

    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other":
        next_state = DEFAULT_TRANSITIONS[detected_intent]
        previous_state = session.state

    else:
        next_state = ChatState.FUERA_DE_FLUJO
        previous_state = session.state

    # --------------------------------------
    # Manejo especial: Salto de Confirmar Componentes
    # --------------------------------------
    if next_state == ChatState.CONFIRMAR_COMPONENTES and session.folio:
        venta = obtener_venta_por_folio(db, session.folio)
        if venta and venta.sku_bitacora_v != "PC-MAXICA":
            next_state = ChatState.CONFIRMAR_PAGO_INICIAL

    # --------------------------------------
    # Manejo especial: Componentes faltantes
    # --------------------------------------
    if current_state == ChatState.COMPONENTES_FALTANTES:

        # Mapear botón a nombre real
        componentes_map = {
            "FALT_CPU": "CPU roja",
            "FALT_MONITOR": "Monitor",
            "FALT_TECLADO": "Teclado",
            "FALT_MOUSE": "Mouse",
            "FALT_BOCINAS": "Bocinas",
            "FALT_REGULADOR": "Regulador",
            "FALT_WIFI": "Antena WiFi",
        }

        if detected_intent in componentes_map:

            componente = componentes_map[detected_intent]

            # Inicializar extra_data si no existe
            if not session.extra_data:
                session.extra_data = {}

            faltantes = session.extra_data.get("faltantes", [])

            # Evitar duplicados
            if componente not in faltantes:
                faltantes.append(componente)

            session.extra_data["faltantes"] = faltantes

            next_state = ChatState.COMPONENTES_CONFIRMAR_FALTANTES

            reply = (
                "Has seleccionado:\n\n• "
                + "\n• ".join(faltantes)
                + "\n\n¿Deseas agregar otro componente faltante?"
            )

            return FlowResult(
                reply,
                next_state,
                FLOW[next_state].get("buttons", []),
                previous_state,
            )

    # --------------------------------------
    # Render dinámico del siguiente estado
    # --------------------------------------     

    next_flow = FLOW.get(next_state, {})

    reply = next_flow.get("text", "")
    image_id = None

    # Si requiere datos de SIGA
    if session.folio:

        venta = obtener_venta_por_folio(db, session.folio)

        if next_state == ChatState.CONFIRMAR_FOLIO:
            reply = f"🔎 Detecté tu folio: *{session.folio}*\n\n¿Es correcto?"

        elif next_state == ChatState.CONFIRMAR_NOMBRE:
            reply = MessageBuilder.confirmar_nombre(
                construir_nombre(venta)
            )

        elif next_state == ChatState.CONFIRMAR_DOMICILIO:
            domicilio = obtener_domicilio_por_movimiento(db, venta.id_movimiento_bv)
            reply = MessageBuilder.confirmar_domicilio(
                address_formatter.construir_domicilio(domicilio)
            )

        elif next_state == ChatState.CONFIRMAR_FECHA:
            fecha_natural = (
                formatear_fecha_larga(venta.fecha_venta)
                if venta.fecha_venta else "No disponible"
            )
            reply = MessageBuilder.confirmar_fecha(fecha_natural)

        elif next_state == ChatState.CONFIRMAR_PRODUCTO:
            reply = MessageBuilder.confirmar_producto(
                construir_producto(venta)
            )

        elif next_state == ChatState.INFO_PAGOS:
            calculos = calcular_info_pagos(venta)
            if calculos:
                reply = MessageBuilder.info_pagos(
                    fecha_limite=calculos["fecha_limite"],
                    pago_minimo=calculos["pago_minimo"],
                    importe_quincenal=calculos["importe_quincenal"],
                    importe_mensual=calculos["importe_mensual"],
                )
        
        elif next_state == ChatState.INFO_METODOS_PAGO:
            reply = MessageBuilder.info_metodos_pago(
                construir_no_cuenta(venta)
            )
            image_id = settings.METODOS_PAGO_IMAGE_ID

        elif next_state == ChatState.INFO_PLAN_3_MESES:
            calculos_3m = calcular_info_plan_3_meses(venta)
            if calculos_3m:
                reply = MessageBuilder.info_plan_3_meses(
                    saldo_3_meses=calculos_3m["saldo_3_meses"],
                    fecha_limite_3_meses=calculos_3m["fecha_limite_3_meses"],
                    importe_semanal_3m=calculos_3m["importe_semanal_3m"],
                    subsidio=calculos_3m["subsidio"] if calculos_3m["tiene_subsidio"] else None,
                )


    print(f"DEBUG: current_state={current_state}, detected_intent={detected_intent}, next_state={next_state}, previous_state={previous_state}")
    return FlowResult(
        reply,
        next_state,
        next_flow.get("buttons", []),
        previous_state,
        image_id
    )
