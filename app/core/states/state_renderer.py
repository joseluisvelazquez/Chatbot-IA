from app.core.flow.flow import FLOW
from app.core.states.states import ChatState
from app.content import messages as content_messages
from app.content.message_builder import MessageBuilder

import logging
import re

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
from app.services.siga_bridge_sale import (
    bridge_address_from_session,
    bridge_sale_from_session,
    get_cached_bridge_verification_payload,
    is_bridge_sale,
    normalize_siga_verification_snapshot,
)

from app.utils.product_mapping import get_product_info_for_sale

logger = logging.getLogger(__name__)

RENDER_DATA_REQUIRED_STATES = {
    ChatState.INICIO,
    ChatState.INICIO2,
    ChatState.CONFIRMAR_NOMBRE,
    ChatState.CONFIRMAR_DOMICILIO,
    ChatState.CONFIRMAR_FECHA,
    ChatState.CONFIRMAR_PRODUCTO,
    ChatState.CONFIRMAR_ESTADO_PRODUCTO,
    ChatState.CONFIRMAR_PAGO_INICIAL,
    ChatState.INFO_PAGOS,
    ChatState.INFO_METODOS_PAGO,
    ChatState.INFO_PLAN_3_MESES,
    ChatState.INFO_BENEFICIOS2,
}


def _mask(value, *, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _has_render_value(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"-", "null", "none", "undefined", "no disponible"}


def _reply_has_unresolved_placeholder(reply: str | None) -> bool:
    return bool(reply and re.search(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", reply))


def _sale_for_session(session, db):
    if not getattr(session, "folio", None):
        return None

    venta = obtener_venta_por_folio(db, session.folio) if db else None
    if not venta:
        venta = bridge_sale_from_session(session, session.folio)
    return venta


def _missing_fields_for_state(next_state, session, db, venta=None) -> list[str]:
    if next_state not in RENDER_DATA_REQUIRED_STATES:
        return []

    venta = venta or _sale_for_session(session, db)
    if not venta:
        return ["venta_snapshot"]

    missing: list[str] = []

    if next_state in {ChatState.INICIO, ChatState.INICIO2, ChatState.CONFIRMAR_NOMBRE}:
        if not _has_render_value(getattr(venta, "nombre_completo", None)):
            missing.append("nombre_completo")

    elif next_state == ChatState.CONFIRMAR_DOMICILIO:
        if is_bridge_sale(venta):
            domicilio_texto = bridge_address_from_session(session, session.folio)
        else:
            domicilio = obtener_domicilio_por_movimiento(db, venta.id_movimiento_bv) if db else None
            domicilio_texto = address_formatter.construir_domicilio(domicilio) if domicilio else None
        if not _has_render_value(domicilio_texto):
            missing.append("domicilio_completo")

    elif next_state == ChatState.CONFIRMAR_FECHA:
        if not _has_render_value(getattr(venta, "fecha_venta", None)):
            missing.append("fecha_venta")

    elif next_state in {ChatState.CONFIRMAR_PRODUCTO, ChatState.CONFIRMAR_ESTADO_PRODUCTO, ChatState.INFO_BENEFICIOS2}:
        info = get_product_info_for_sale(venta)
        product_name = info.get("nombre_amigable")
        if not _has_render_value(product_name) or str(product_name).strip().lower() == "producto":
            missing.append("nombre_producto")

    elif next_state == ChatState.CONFIRMAR_PAGO_INICIAL:
        if not _has_render_value(getattr(venta, "pago", None)):
            missing.append("importe_pago_inicial")

    elif next_state == ChatState.INFO_PAGOS:
        calculos = calcular_info_pagos(venta)
        required = ("fecha_limite", "pago_minimo", "importe_quincenal", "importe_mensual")
        missing.extend(key for key in required if not _has_render_value((calculos or {}).get(key)))

    elif next_state == ChatState.INFO_METODOS_PAGO:
        if not _has_render_value(construir_no_cuenta(venta)):
            missing.append("numero_cuenta")

    elif next_state == ChatState.INFO_PLAN_3_MESES:
        calculos_3m = calcular_info_plan_3_meses(venta)
        required = ("saldo_3_meses", "fecha_limite_3_meses", "importe_semanal_3m")
        missing.extend(key for key in required if not _has_render_value((calculos_3m or {}).get(key)))

    return missing


def get_missing_render_fields(next_state, session, db) -> list[str]:
    return _missing_fields_for_state(next_state, session, db)


def _render_missing_data(next_state, session, missing_fields: list[str]):
    logger.warning(
        "verification_render_blocked_missing_data",
        extra={
            "session_id": getattr(session, "id", None),
            "state": getattr(next_state, "value", str(next_state)),
            "folio_masked": _mask(getattr(session, "folio", None)),
            "missing_fields": missing_fields,
        },
    )
    return content_messages.DATOS_VERIFICACION_PREPARANDO, [], None


def _snapshot_from_session(session) -> dict | None:
    if not getattr(session, "folio", None):
        return None
    payload = get_cached_bridge_verification_payload(session, session.folio)
    if not isinstance(payload, dict):
        return None
    snapshot = normalize_siga_verification_snapshot(payload)
    return snapshot if isinstance(snapshot, dict) else None


def _comprobante_access_values(session, venta) -> tuple[str | None, str | None]:
    numero_cuenta = construir_no_cuenta(venta) if venta else None
    codigo_cliente = getattr(venta, "codigo_cliente", None) if venta else None

    snapshot = getattr(venta, "_bridge_payload", None) if venta else None
    if not isinstance(snapshot, dict):
        snapshot = _snapshot_from_session(session)

    if isinstance(snapshot, dict):
        if not _has_render_value(numero_cuenta):
            numero_cuenta = snapshot.get("no_cuenta")
        if not _has_render_value(codigo_cliente):
            codigo_cliente = snapshot.get("codigo_cliente")

    return numero_cuenta, codigo_cliente


def _render_comprobante_acceso(session, venta) -> str:
    numero_cuenta, codigo_cliente = _comprobante_access_values(session, venta)
    reply = MessageBuilder.info_comprobante_acceso(numero_cuenta, codigo_cliente)
    if reply == content_messages.INFO_COMPROBANTE_ACCESO_FALLBACK:
        logger.warning(
            "comprobante_access_data_unavailable",
            extra={
                "session_id": getattr(session, "id", None),
                "folio_masked": _mask(getattr(session, "folio", None)),
                "has_numero_cuenta": _has_render_value(numero_cuenta),
                "has_codigo_cliente": _has_render_value(codigo_cliente),
            },
        )
    return reply


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

    venta = _sale_for_session(session, db)

    # --------------------------------------
    # Render dinámico por estado
    # --------------------------------------

    if next_state in [ChatState.CONFIRMAR_FOLIO_DEVOLUCION, ChatState.CONFIRMAR_FOLIO_DESCUENTO]:
        from app.content import messages as msg
        reply = msg.CONFIRMAR_FOLIO_DETECTADO.format(folio=session.folio)

    if next_state == ChatState.INFO_COMPROBANTE_ACCESO:
        reply = _render_comprobante_acceso(session, venta)
        image_id = settings.get_asset_url(settings.VIDEO_ID_COMPROBANTES)

    missing_fields = _missing_fields_for_state(next_state, session, db, venta)
    if missing_fields:
        return _render_missing_data(next_state, session, missing_fields)

    if not venta:
        if _reply_has_unresolved_placeholder(reply):
            return _render_missing_data(next_state, session, ["unresolved_placeholder"])
        return reply, buttons, image_id

    if next_state == ChatState.RETO_SEGURIDAD:
        from app.content import messages as msg
        reply = msg.RETO_SEGURIDAD_SOLICITUD.format(folio=session.folio)

    elif next_state in [ChatState.INICIO, ChatState.INICIO2]:
        nombre = construir_nombre(venta)
        if not _has_render_value(nombre):
            return _render_missing_data(next_state, session, ["nombre_completo"])
        reply = reply.format(nombre_completo=nombre)

    elif next_state == ChatState.CONFIRMAR_NOMBRE:
        if not _has_render_value(construir_nombre(venta)):
            return _render_missing_data(next_state, session, ["nombre_completo"])
        reply = MessageBuilder.confirmar_nombre(
            construir_nombre(venta)
        )

    elif next_state == ChatState.CONFIRMAR_PAGO_INICIAL:
        pago_inicial = construir_pago_inicial(venta)
        if not _has_render_value(getattr(venta, "pago", None)):
            return _render_missing_data(next_state, session, ["importe_pago_inicial"])
        else:
            reply = MessageBuilder.confirmar_pago(pago_inicial)

    elif next_state == ChatState.CONFIRMAR_DOMICILIO:
        if is_bridge_sale(venta):
            domicilio_texto = bridge_address_from_session(session, session.folio)
        else:
            domicilio = obtener_domicilio_por_movimiento(
                db,
                venta.id_movimiento_bv
            )
            domicilio_texto = address_formatter.construir_domicilio(domicilio)

        reply = MessageBuilder.confirmar_domicilio(
            domicilio_texto
        )

    elif next_state == ChatState.CONFIRMAR_FECHA:
        fecha_natural = (
            formatear_fecha_larga(venta.fecha_venta)
            if venta.fecha_venta else "No disponible"
        )

        reply = MessageBuilder.confirmar_fecha(fecha_natural)

    elif next_state == ChatState.CONFIRMAR_PRODUCTO:
        info = get_product_info_for_sale(venta)
        reply = MessageBuilder.confirmar_producto(info["articulo"], info["nombre_amigable"])

    elif next_state == ChatState.CONFIRMAR_ESTADO_PRODUCTO:
        info = get_product_info_for_sale(venta)
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
        else:
            return _render_missing_data(next_state, session, ["pagos"])

    elif next_state == ChatState.INFO_METODOS_PAGO:
        reply = MessageBuilder.info_metodos_pago(
            construir_no_cuenta(venta)
        )
        image_id = settings.get_asset_url(settings.METODOS_PAGO_IMAGE_ID)

    elif next_state == ChatState.INFO_COMPROBANTE_ACCESO:
        reply = _render_comprobante_acceso(session, venta)
        image_id = settings.get_asset_url(settings.VIDEO_ID_COMPROBANTES)

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
        else:
            return _render_missing_data(next_state, session, ["plan3meses"])

    elif next_state == ChatState.INFO_BENEFICIOS2:
        info = get_product_info_for_sale(venta)
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
                filename = getattr(settings, env_var, None)
                image_id = settings.get_asset_url(filename)

    elif next_state == ChatState.INCONSISTENCIA:
        from app.content import messages as msg
        
        # El origen de la inconsistencia es el estado actual de la sesión, no el anterior
        origen = str(session.state) if session.state != ChatState.INCONSISTENCIA else str(session.previous_state)
        
        inconsistencia_map = {
            ChatState.INICIO.value: msg.INCONSISTENCIA_NOMBRE,
            ChatState.INICIO2.value: msg.INCONSISTENCIA_NOMBRE,
            ChatState.CONFIRMAR_NOMBRE.value: msg.INCONSISTENCIA_NOMBRE,
            ChatState.CONFIRMAR_DOMICILIO.value: msg.INCONSISTENCIA_DOMICILIO,
            ChatState.CONFIRMAR_FECHA.value: msg.INCONSISTENCIA_FECHA,
            ChatState.CONFIRMAR_PRODUCTO.value: msg.INCONSISTENCIA_PRODUCTO,
            ChatState.CONFIRMAR_ESTADO_PRODUCTO.value: msg.INCONSISTENCIA_ESTADO_PRODUCTO,
            ChatState.CONFIRMAR_PAGO_INICIAL.value: msg.INCONSISTENCIA_PAGO_INICIAL,
        }
        
        reply = inconsistencia_map.get(origen, msg.INCONSISTENCIA)

    if _reply_has_unresolved_placeholder(reply):
        return _render_missing_data(next_state, session, ["unresolved_placeholder"])

    return reply, buttons, image_id
