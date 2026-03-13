from __future__ import annotations

from dataclasses import dataclass
import logging

from app.content.message_builder import MessageBuilder
from app.core.flow import DEFAULT_TRANSITIONS, FLOW
from app.core.intents import detect_intent
from app.core.states import ChatState
from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
from app.services import verification_service
from app.services.verification_service import VerificationService
from app.services.verification_tracker import track_verification
from app.siga.siga_repository import (
    obtener_venta_por_folio,
    obtener_domicilio_por_movimiento,
    construir_nombre,
    construir_pago_inicial,
    construir_producto,
    construir_no_cuenta,
)
from app.utils.date_formatter import formatear_fecha_larga
from app.content import messages
from app.pricing.payment_plans import calcular_info_pagos, calcular_info_plan_3_meses
from app.utils.date_formatter import formatear_fecha_larga
from app.utils import address_formatter
from app.services.inconsistencias_service import get_open_inconsistencia
from app.utils.folio_parser import extraer_folio

# Mapeo de SKU a nombre de producto por que se maneja diferente en SIGA (Ta raro esto ayuda mucho lit good)
SKU_PRODUCT_MAP = {
    "14DQ6011DX": "Laptop HP",
    "MULTI-MX-2": "Impresora multifuncional HP Smart Tank",
    "MULTI-MX-1": "Multifuncional Brother",
}

# Mapeo de componentes faltantes para facilitar su registro y manejo Para que salga en el whatsap con emojis y no se registre con simbolos raros en el json tambien good
COMPONENTES_MAP = {
    "FALT_CPU": {
        "db": "CPU roja",
        "label": "🔴 CPU roja"
    },
    "FALT_MONITOR": {
        "db": "Monitor",
        "label": "🖥️ Monitor"
    },
    "FALT_TECLADO": {
        "db": "Teclado",
        "label": "⌨️ Teclado"
    },
    "FALT_MOUSE": {
        "db": "Mouse",
        "label": "🖱️ Mouse"
    },
    "FALT_BOCINAS": {
        "db": "Bocinas",
        "label": "🔊 Bocinas"
    },
    "FALT_REGULADOR": {
        "db": "Regulador",
        "label": "🔌 Regulador"
    },
    "FALT_WIFI": {
        "db": "Antena WiFi",
        "label": "📶 Antena WiFi"
    },
}

INCONSISTENCIAS_MAP = {
    ChatState.CONFIRMAR_NOMBRE: "nombre",
    ChatState.CONFIRMAR_DOMICILIO: "domicilio",
    ChatState.CONFIRMAR_FECHA: "fecha_venta",
    ChatState.CONFIRMAR_PRODUCTO: "producto",
    ChatState.CONFIRMAR_PAGO_INICIAL: "pago_inicial",
}
TRANSITIONS = [
            ChatState.INCONSISTENCIA,
            ChatState.ESCRIBIR_INCONSISTENCIA,
            ChatState.FUERA_DE_FLUJO,
            ChatState.ACLARACION,
            ChatState.LLAMADA,
            ChatState.RECORDATORIO_1H,
            ChatState.RECORDATORIO_2H,
        ]
from app.config.settings import settings


@dataclass
class FlowResult:
    reply: str
    next_state: ChatState
    buttons: list
    previous_state: str | None = None
    inconsistencia_patch: dict | None = None    
    image_id: str | None = None


def process_message(session, text: str, intent: str | None = None, db=None) -> FlowResult:
    current_state = ChatState(session.state)
    previous_state = session.previous_state
    flow = FLOW.get(current_state)
    print(f"DEBUG: Processing message for session {session.id} in state {current_state} with text '{text}' and intent '{intent}'")

    if not flow:
        return FlowResult("Un asesor te contactará.", ChatState.LLAMADA, [])
    no_cuenta = VerificationService(db).resolve_no_cuenta_from_folio(session.folio)

    if no_cuenta:

        if verification_service.is_verification_complete(no_cuenta):
            return {
                "text": "✅ Esta cuenta ya fue verificada anteriormente.",
                "buttons": [
                    {"id": "DUDA", "label": "❓ Tengo una duda"},
                    {"id": "PAGOS", "label": "💳 Consultar pagos"}
                ]
            }
    
    

    # --------------------------------------
    # Helpers internos: persistencia best-effort (no rompe flujo si falla)
    # --------------------------------------
    logger = logging.getLogger(__name__)

    def _try_mark_step(step_key: str) -> None:
        if db is None:
            return
        folio = getattr(session, "folio", None)
        if not folio:
            return
        try:
            VerificationService(db).mark_step_from_folio(str(folio), step_key, 1)
        except Exception as e:
            logger.exception("No se pudo marcar progreso verificación step=%s folio=%s", step_key, folio)
            return

    # --------------------------------------
    # Detectar intención
    # --------------------------------------
    if intent:
        detected_intent = intent
        folio = None
    else:
        detected_intent, folio = detect_intent(text, current_state)

    # --------------------------------------
    # Detectar folio en cualquier mensaje
    # --------------------------------------

    folio_detectado = extraer_folio(text)

    if folio_detectado and not session.folio:

        venta = obtener_venta_por_folio(db, folio_detectado)

        if venta:
            session.folio = folio_detectado

            return FlowResult(
                reply=f"🔎 Detecté tu folio: *{folio_detectado}*\n\n¿Es correcto?",
                next_state=ChatState.CONFIRMAR_FOLIO,
                buttons=FLOW[ChatState.CONFIRMAR_FOLIO].get("buttons", []),
                previous_state=None
            )

    # --------------------------------------
    # Mostrar menú principal
    # --------------------------------------

    if current_state in [ChatState.ESPERA, ChatState.FUERA_DE_FLUJO] and detected_intent != "start_verification":
        return FlowResult(
            reply=messages.MENU_AYUDA,
            next_state=ChatState.MENU_AYUDA,
            buttons=FLOW[ChatState.MENU_AYUDA]["buttons"]
        )
    
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

        session.folio = folio

        _try_mark_step("inicio")
        _try_mark_step("folio")
        return FlowResult(
            reply=f"🔎 Detecté tu folio: *{folio}*\n\n¿Es correcto?",
            next_state=ChatState.CONFIRMAR_FOLIO,
            buttons=FLOW[ChatState.CONFIRMAR_FOLIO].get("buttons", []),
            previous_state=None
        )

    # --------------------------------------
    # Cambio manual de folio
    # --------------------------------------
    elif current_state == ChatState.CAMBIAR_FOLIO:

        nuevo_folio = extraer_folio(text)

        if not nuevo_folio:
            return FlowResult(
                "❌ No pude detectar un folio válido.\n\n✏️ Envíalo nuevamente.",
                current_state,
                [],
                previous_state,
            )

        venta = obtener_venta_por_folio(db, nuevo_folio)

        if not venta:
            return FlowResult(
                "❌ Ese folio no existe.\n\n✏️ Intenta nuevamente.",
                current_state,
                [],
                previous_state,
            )

        session.folio = nuevo_folio
        _try_mark_step("folio")


        return FlowResult(
            reply=f"🔎 Detecté tu folio: *{nuevo_folio}*\n\n¿Es correcto?",
            next_state=ChatState.CONFIRMAR_FOLIO,
            buttons=FLOW[ChatState.CONFIRMAR_FOLIO].get("buttons", []),
            previous_state=None
        )
        

    # --------------------------------------
    # Usuario escribe la inconsistencia
    # --------------------------------------

    if current_state == ChatState.ESCRIBIR_INCONSISTENCIA:

        campo = INCONSISTENCIAS_MAP.get(ChatState(previous_state))

        if campo:
            return FlowResult(
                reply="Gracias, un asesor revisará la información.",
                next_state=ChatState.INCONSISTENCIA,
                buttons=FLOW[ChatState.INCONSISTENCIA].get("buttons", []),
                previous_state=previous_state,
                inconsistencia_patch={
                    campo: {
                        "confirmado": False,
                        "mensaje_cliente": text
                    }
                }
            )
        
    # --------------------------------------
    # Transiciones normales
    # --------------------------------------}
    elif detected_intent in flow.get("options", {}):
        next_state = flow["options"][detected_intent]
        
        track_verification(
            db=db,
            session=session,
            current_state=current_state,
            detected_intent=detected_intent,
            next_state=next_state
        )

        
        # Guardar estado anterior si vamos a inconsistencia o similares
        if next_state in TRANSITIONS and current_state not in TRANSITIONS:
            previous_state = session.state

        if next_state == "__RESUME__":
            if previous_state:
                prev = ChatState(previous_state)

                # ✅ Si venimos de una pregunta "confirmable" (nombre/domicilio/fecha/producto/pago)
                # avanzamos a la siguiente pregunta (la del "affirmative")
                if prev in INCONSISTENCIAS_MAP:
                    opts = FLOW.get(prev, {}).get("options", {})
                    next_state = opts.get("affirmative") or opts.get(f"{prev.name.split('_')[1]}_SI") or prev
                else:
                    # fallback normal
                    next_state = prev
            else:
                next_state = ChatState.INICIO

    elif detected_intent in DEFAULT_TRANSITIONS and detected_intent != "other" and current_state not in TRANSITIONS:
        next_state = DEFAULT_TRANSITIONS[detected_intent]
        previous_state = session.state

    else:
        next_state = ChatState.FUERA_DE_FLUJO
        if current_state not in TRANSITIONS:
            previous_state = session.state
    print(f"DEBUG: current_state={current_state}, detected_intent={detected_intent}, next_state={next_state}, previous_state={previous_state}")

   

    # --------------------------------------
    # Manejo especial: Salto de Confirmar Componentes
    # --------------------------------------
    if next_state == ChatState.CONFIRMAR_COMPONENTES and session.folio:
        venta = obtener_venta_por_folio(db, session.folio)
        if venta and venta.sku_bitacora_v != "PC-MAXICA":
            next_state = ChatState.CONFIRMAR_ESTADO_PRODUCTO

    # --------------------------------------
    # Manejo especial: Beneficios según producto
    # --------------------------------------
    if next_state == ChatState.INFO_BENEFICIOS and session.folio:
        venta = obtener_venta_por_folio(db, session.folio)

        if venta and venta.sku_bitacora_v != "PC-MAXICA":
            next_state = ChatState.INFO_BENEFICIOS2

    # --------------------------------------
    # Registrar componente faltante
    # --------------------------------------

    if detected_intent in COMPONENTES_MAP:
        componente_db = COMPONENTES_MAP[detected_intent]["db"]
        componente_label = COMPONENTES_MAP[detected_intent]["label"]

        next_state = ChatState.COMPONENTES_CONFIRMAR_FALTANTES

        reply = f"✅ Agregado: *{componente_label}*\n\n¿Deseas agregar otro componente faltante?"

        return FlowResult(
            reply=reply,
            next_state=next_state,
            buttons=FLOW[next_state].get("buttons", []),
            previous_state=previous_state,
            inconsistencia_patch={
                "componentes": {
                    "faltantes_append": [componente_db]
                }
            },
        )

    # --------------------------------------
    # Manejo especial: Componentes faltantes
    # --------------------------------------

    if next_state == ChatState.COMPONENTES_FALTANTES:
        componentes_seleccionados = []

        inc = get_open_inconsistencia(
            db=db,
            phone=session.phone,
            folio=session.folio,
            session_id=session.id
        )

        if inc and inc.extra_json:
            componentes_seleccionados = (
                inc.extra_json
                .get("componentes", {})
                .get("faltantes", [])
            )

        # Filtrar los ya seleccionados
        componentes_disponibles = {
            k: v
            for k, v in COMPONENTES_MAP.items()
            if v["db"] not in componentes_seleccionados
        }

        # --------------------------------------
        # Si ya seleccionó todos los componentes
        # --------------------------------------

        if not componentes_disponibles:

            faltantes_texto = "\n".join(f"• {c}" for c in componentes_seleccionados)
            reply = f"""📋 Registramos estos componentes faltantes:
            {faltantes_texto}
            🔧 Un asesor revisará tu caso."""

            return FlowResult(
                reply=reply,
                next_state=ChatState.CONFIRMAR_PAGO_INICIAL,
                buttons=FLOW[ChatState.CONFIRMAR_PAGO_INICIAL].get("buttons", []),
                previous_state=previous_state
            )

        buttons = [
            {"id": k, "label": v["label"]}
            for k, v in componentes_disponibles.items()
        ]

        return FlowResult(
            reply="Selecciona el componente que faltó:",
            next_state=ChatState.COMPONENTES_FALTANTES,
            buttons=buttons,
            previous_state=previous_state
        )
    
    # --------------------------------------
    # Render dinámico del siguiente estado
    # --------------------------------------
    next_flow = FLOW.get(next_state, {})
    result_patch = None
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
        elif next_state == ChatState.CONFIRMAR_PAGO_INICIAL:
            reply = MessageBuilder.confirmar_pago(
                construir_pago_inicial(venta)
            )

        elif next_state == ChatState.CONFIRMAR_DOMICILIO:
            domicilio = obtener_domicilio_por_movimiento(db, venta.id_movimiento_bv)
            reply = MessageBuilder.confirmar_domicilio(
                address_formatter.construir_domicilio(domicilio)
            )

        elif next_state == ChatState.CONFIRMAR_FECHA:
            fecha_natural = (
                formatear_fecha_larga(venta.fecha_venta) if venta.fecha_venta else "No disponible"
            )
            reply = MessageBuilder.confirmar_fecha(fecha_natural)

        elif next_state == ChatState.CONFIRMAR_PRODUCTO:
            sku = venta.sku_bitacora_v.upper()
            producto = SKU_PRODUCT_MAP.get(sku, sku)

            reply = MessageBuilder.confirmar_producto(producto)
        
        elif next_state == ChatState.CONFIRMAR_ESTADO_PRODUCTO:
            sku = venta.sku_bitacora_v.upper()
            producto = SKU_PRODUCT_MAP.get(sku, sku)

            reply = MessageBuilder.confirmar_estado_producto(producto)

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
        
        elif next_state == ChatState.INFO_BENEFICIOS2:
            sku = venta.sku_bitacora_v.upper()
            producto = SKU_PRODUCT_MAP.get(sku, sku)

            reply = MessageBuilder.info_beneficios2(producto)


    print(f"DEBUG: current_state={current_state}, detected_intent={detected_intent}, next_state={next_state}, previous_state={previous_state}")
    return FlowResult(
        reply=reply,
        next_state=next_state,
        buttons=next_flow.get("buttons", []),
        previous_state=previous_state,
        inconsistencia_patch=result_patch,
        image_id=image_id
    )
