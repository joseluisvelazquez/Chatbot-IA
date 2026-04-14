from app.core.flow.flow import FLOW
from app.core.states.states import ChatState
from app.content.message_builder import MessageBuilder

from app.siga.siga_repository import (
    obtener_venta_por_folio,
    obtener_domicilio_por_movimiento,
    construir_nombre,
    construir_pago_inicial,
    construir_no_cuenta,
)

from app.pricing.payment_plans import (
    calcular_info_pagos,
    calcular_info_plan_3_meses,
)

from app.utils.date_formatter import formatear_fecha_larga
from app.utils import address_formatter
from app.config.settings import settings
from app.services.inconsistencias_service import get_open_inconsistencia
from app.core.states.state_handlers import COMPONENTES_MAP, _get_componentes_ya_reportados

from app.utils.product_mapping import get_product_info

def render_state(next_state, session, db):
    """
    Construye el mensaje dinámico del estado.
    Devuelve:
    - reply
    - buttons
    - image_id
    """

    flow = FLOW.get(next_state, {})
    reply = flow.get("text", "")
    buttons = flow.get("buttons", [])
    image_id = None

    venta = None

    # --------------------------------------
    # Obtener datos de SIGA si hay folio
    # --------------------------------------
    if session.folio:
        venta = obtener_venta_por_folio(db, session.folio)

    # --------------------------------------
    # Render dinámico por estado
    # --------------------------------------

    if not venta:
        return reply, buttons, image_id

    if next_state in [ChatState.CONFIRMAR_FOLIO, ChatState.CONFIRMAR_FOLIO_DEVOLUCION, ChatState.CONFIRMAR_FOLIO_DESCUENTO]:
        from app.content import messages as msg
        reply = msg.CONFIRMAR_FOLIO_DETECTADO.format(folio=session.folio)

    elif next_state == ChatState.CONFIRMAR_NOMBRE:
        reply = MessageBuilder.confirmar_nombre(
            construir_nombre(venta)
        )

    elif next_state == ChatState.CONFIRMAR_PAGO_INICIAL:
        reply = MessageBuilder.confirmar_pago(
            construir_pago_inicial(venta)
        )

    elif next_state == ChatState.CONFIRMAR_DOMICILIO:
        domicilio = obtener_domicilio_por_movimiento(
            db,
            venta.id_movimiento_bv
        )

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
        info = get_product_info(venta.sku_bitacora_v)
        reply = MessageBuilder.confirmar_producto(info["articulo"], info["nombre_amigable"])

    elif next_state == ChatState.CONFIRMAR_ESTADO_PRODUCTO:
        info = get_product_info(venta.sku_bitacora_v)
        reply = MessageBuilder.confirmar_estado_producto(info["nombre_amigable"])

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
                subsidio=calculos_3m["subsidio"]
                if calculos_3m["tiene_subsidio"] else None,
            )

    elif next_state == ChatState.INFO_BENEFICIOS2:
        info = get_product_info(venta.sku_bitacora_v)
        reply = MessageBuilder.info_beneficios2(info["nombre_amigable"])

    elif next_state == ChatState.DEVOLUCION_CONFIRMAR:
        reply = MessageBuilder.build_devolucion_confirmacion()

    elif next_state == ChatState.COMPONENTES_FALTANTES:
        inc = get_open_inconsistencia(
            db=db,
            phone=session.phone,
            folio=session.folio,
            session_id=session.id
        )
        seleccionados = []
        if inc and inc.extra_json:
            seleccionados = _get_componentes_ya_reportados(inc.extra_json)
            
        disponibles = {
            k: v for k, v in COMPONENTES_MAP.items()
            if v["db"] not in seleccionados
        }

        buttons = [{"id": k, "label": v["label"]} for k, v in disponibles.items()]
    elif next_state == ChatState.VERIFICAR_FOTO_COMPONENTE:
        intent_comp = getattr(session, "componente_en_verificacion", None)

        if not intent_comp:
            inc = get_open_inconsistencia(db, session.phone, session.folio, session.id)
            if inc and inc.extra_json:
                intent_comp = inc.extra_json.get("componentes_temp", {}).get("componente_en_verificacion")

        if intent_comp and intent_comp in COMPONENTES_MAP:
            componente = COMPONENTES_MAP[intent_comp]
            reply = f"Te envío una foto de referencia de: *{componente['label']}*.\n\nPor favor revisa bien tu paquete, ¿estás absolutamente seguro de que NO lo recibiste?"
            
            env_var = componente.get("image_env")
            if env_var:
                image_id = getattr(settings, env_var, None)

    elif next_state == ChatState.INCONSISTENCIA:
        from app.content import messages as msg
        
        # El origen de la inconsistencia es el estado actual de la sesión, no el anterior
        origen = str(session.state) if session.state != ChatState.INCONSISTENCIA else str(session.previous_state)
        
        inconsistencia_map = {
            ChatState.CONFIRMAR_NOMBRE.value: msg.INCONSISTENCIA_NOMBRE,
            ChatState.CONFIRMAR_DOMICILIO.value: msg.INCONSISTENCIA_DOMICILIO,
            ChatState.CONFIRMAR_FECHA.value: msg.INCONSISTENCIA_FECHA,
            ChatState.CONFIRMAR_PRODUCTO.value: msg.INCONSISTENCIA_PRODUCTO,
            ChatState.CONFIRMAR_ESTADO_PRODUCTO.value: msg.INCONSISTENCIA_ESTADO_PRODUCTO,
            ChatState.CONFIRMAR_PAGO_INICIAL.value: msg.INCONSISTENCIA_PAGO_INICIAL,
        }
        
        reply = inconsistencia_map.get(origen, msg.INCONSISTENCIA)

    return reply, buttons, image_id