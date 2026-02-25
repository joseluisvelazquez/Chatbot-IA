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
    construir_domicilio,
    obtener_venta_por_folio,
    obtener_domicilio_por_movimiento,
    construir_nombre,
)
from app.content.message_builder import MessageBuilder

@dataclass
class FlowResult:
    reply: str
    next_state: ChatState
    buttons: list
    previous_state: str | None = None

def process_message(session, text: str, intent: str | None = None, db=None) -> FlowResult:

    current_state = ChatState(session.state)
    previous_state = session.previous_state
    flow = FLOW.get(current_state)

    if not flow:
        return FlowResult(
            "Un asesor te contactará.",
            ChatState.LLAMADA,
            []
        )

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
        next_state = ChatState.CONFIRMAR_NOMBRE

        reply = MessageBuilder.confirmar_nombre(
            construir_nombre(venta)
        )

        return FlowResult(
            reply,
            next_state,
            FLOW[next_state].get("buttons", []),
        )

    # --------------------------------------
    # Transiciones normales
    # --------------------------------------
    if detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]

        if next_state == "__RESUME__":
            next_state = ChatState(previous_state) if previous_state else ChatState.INICIO

    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other":
        next_state = DEFAULT_TRANSITIONS[detected_intent]

    else:
        next_state = ChatState.FUERA_DE_FLUJO

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
            )

    # --------------------------------------
    # Render dinámico del siguiente estado
    # --------------------------------------

        elif next_state == ChatState.CONFIRMAR_PRODUCTO:
            reply = MessageBuilder.confirmar_producto(
                venta.descripcion or "No disponible"
            )

    reply = next_flow.get("text", "")

    # Si requiere datos de SIGA
    if session.folio:

        venta = obtener_venta_por_folio(db, session.folio)

        if next_state == ChatState.CONFIRMAR_NOMBRE:
            reply = MessageBuilder.confirmar_nombre(
                construir_nombre(venta)
            )

        elif next_state == ChatState.CONFIRMAR_DOMICILIO:
            domicilio = obtener_domicilio_por_movimiento(
                db,
                venta.id_movimiento_bv
            )
            reply = MessageBuilder.confirmar_domicilio(
                construir_domicilio(domicilio, db)
            )

        elif next_state == ChatState.CONFIRMAR_FECHA:
            reply = MessageBuilder.confirmar_fecha(
                venta.fecha_venta.strftime("%d/%m/%Y")
                if venta.fecha_venta else "No disponible"
            )

        elif next_state == ChatState.CONFIRMAR_PRODUCTO:
            reply = MessageBuilder.confirmar_producto(
                venta.sku_bitacora_v or "No disponible"
            )

    return FlowResult(
        reply,
        next_state,
        next_flow.get("buttons", []),
    )