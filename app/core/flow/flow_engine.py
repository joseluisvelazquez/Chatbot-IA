from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import unicodedata

from app.core.states.states import ChatState
from app.core.intents.intents import detect_intent
from app.core.intents.intent_router import route_intent
from app.core.states.state_resolver import resolve_next_state
from app.core.states.state_renderer import get_missing_render_fields, render_state
from app.core.states.state_handlers import handle_special_cases, handle_flow_skips
from app.core.context.conversation_context import ConversationContext
from app.core.states.state_types import get_state_type
from app.core.flow.flow import FLOW
from app.config.settings import settings

from app.content import messages
from app.content.message_builder import MessageBuilder
from app.services import verification_service
from app.siga.siga_repository import obtener_venta_por_folio, obtener_verificacion_por_no_cuenta
from app.utils.folio_parser import extraer_folio_si_mensaje_de_folio

from app.services.verification_service import VerificationService, log_flow_event
from app.services.verification_tracker import track_verification
from app.core.verification.verification_schema import (
    assert_valid_step,
    is_non_trackable_step,
    is_trackable_step,
)
from app.services.ai.ai_service import analyze_inconsistency, generate_ai_response
from app.services.inconsistencias_service import open_or_patch_inconsistencia
from app.services.session_context import reset_verification_context_for_folio
from app.services.ai.intent_interpreter import interpret_intent_with_ai, should_use_ai, is_doubt, detect_frustration
from app.services.faq.faq_service import find_faq_answer
from app.services.siga_bridge_sale import (
    bridge_sale_from_payload,
    bridge_sale_summary,
    bridge_verification_found,
    get_cached_bridge_verification_payload,
)
from app.services.siga_bridge_cache import upsert_cached_verification
from app.db.models import ChatSessions

logger = logging.getLogger(__name__)


ACTIVE_VERIFICATION_STATES = {
    ChatState.INICIO,
    ChatState.INICIO2,
    ChatState.CONFIRMAR_NOMBRE,
    ChatState.CONFIRMAR_DOMICILIO,
    ChatState.CONFIRMAR_FECHA,
    ChatState.CONFIRMAR_PRODUCTO,
    ChatState.CONFIRMAR_ESTADO_PRODUCTO,
    ChatState.CONFIRMAR_COMPONENTES,
    ChatState.CONFIRMAR_PAGO_INICIAL,
    ChatState.INFO_PAGOS,
    ChatState.INFO_METODOS_PAGO,
    ChatState.INFO_COMPROBANTE_ACCESO,
    ChatState.INFO_PLAN_3_MESES,
    ChatState.INFO_OTROS_PLANES,
    ChatState.INFO_BENEFICIOS,
    ChatState.INFO_BENEFICIOS2,
    ChatState.COMPONENTES_FALTANTES,
    ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
    ChatState.VERIFICAR_FOTO_COMPONENTE,
    ChatState.INCONSISTENCIA,
}

SERVICE_STATES_WITH_VERIFICATION_CONTEXT = {
    ChatState.MENU_AYUDA,
    ChatState.MENU_DUDA,
    ChatState.DUDA,
    ChatState.FUERA_DE_FLUJO,
}

STATES_ALLOW_BARE_FOLIO = {
    ChatState.ESPERA,
    ChatState.CAMBIAR_FOLIO,
    ChatState.CAMBIAR_FOLIO_DEVOLUCION,
    ChatState.CAMBIAR_FOLIO_DESCUENTO,
    ChatState.SELECCIONAR_FOLIO,
    ChatState.MENU_AYUDA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.FINALIZADO,
}

STATES_ALLOW_AUTO_FOLIO = {
    ChatState.ESPERA,
    ChatState.INICIO,
    ChatState.CAMBIAR_FOLIO,
    ChatState.CAMBIAR_FOLIO_DEVOLUCION,
    ChatState.CAMBIAR_FOLIO_DESCUENTO,
    ChatState.MENU_AYUDA,
    ChatState.FUERA_DE_FLUJO,
    ChatState.FINALIZADO,
}


def _classify_doubt_to_info_state(text: str) -> ChatState | None:
    if not text:
        return None
    text_lower = text.lower()
    
    # 1. Comprobante de acceso / mxcomp
    if any(k in text_lower for k in ["comprobante", "mxcomp", "subir ticket", "cargar ticket", "subir pago", "enviar ticket", "subir mi pago", "enviar mi pago"]):
        return ChatState.INFO_COMPROBANTE_ACCESO
        
    # 2. Métodos de pago
    if any(k in text_lower for k in ["opciones para realizar tus pagos", "concepto o referencia", "concepto", "referencia"]):
        return ChatState.INFO_METODOS_PAGO
        
    # 3. Plan 3 meses
    if any(k in text_lower for k in ["3 meses", "tres meses", "saldo a 3 meses", "plan 3", "fecha limite plan 3 meses", "liquidar en 3 meses", "saldo cuenta"]):
        return ChatState.INFO_PLAN_3_MESES
        
    # 4. Otros planes
    if any(k in text_lower for k in ["otros planes", "planes de pago", "cambiar plan", "exceder fecha limite", "precios otros planes"]):
        return ChatState.INFO_OTROS_PLANES
        
    # 5. Pagos (semanal, quincenal, mensual, montos)
    if any(k in text_lower for k in ["semanal", "quincenal", "mensual", "importe minimo", "cuánto pago", "cada cuanto", "primer pago", "pagos quincenales", "pagos mensuales"]):
        return ChatState.INFO_PAGOS
        
    # (Beneficios removido de saltos directos por petición del usuario)        
    # 7. Fallback por IA
    try:
        from app.services.ai.ai_service import generate_raw_ai_response
        prompt = f"""
Clasifica la duda del usuario en uno de los siguientes estados informativos del chatbot:

- INFO_PAGOS: Preguntas sobre los montos de pago (semanal, quincenal, mensual, cuánto tiene que pagar).
- INFO_METODOS_PAGO: Preguntas sobre dónde o cómo pagar, cuentas bancarias, depósitos en OXXO, transferencias SPEI, tarjetas de débito.
- INFO_COMPROBANTE_ACCESO: Preguntas sobre dónde subir el comprobante de pago, el sitio mxcomp.mx, o cómo obtener el código de cliente.
- INFO_PLAN_3_MESES: Preguntas sobre el plan de liquidación a 3 meses (o 13 semanas).
- INFO_OTROS_PLANES: Preguntas sobre plazos más largos o cambio de planes.

Responde ÚNICAMENTE con el nombre exacto del estado en mayúsculas (ej: INFO_METODOS_PAGO) o la palabra NONE si no corresponde a ninguna de las opciones anteriores de forma clara.

Duda del usuario: "{text}"
Respuesta:"""
        res = generate_raw_ai_response(prompt, task="info_classification")
        if res:
            res = res.strip().upper()
            if "INFO_PAGOS" in res:
                return ChatState.INFO_PAGOS
            if "INFO_METODOS_PAGO" in res:
                return ChatState.INFO_METODOS_PAGO
            if "INFO_COMPROBANTE_ACCESO" in res:
                return ChatState.INFO_COMPROBANTE_ACCESO
            if "INFO_PLAN_3_MESES" in res:
                return ChatState.INFO_PLAN_3_MESES
            if "INFO_OTROS_PLANES" in res:
                return ChatState.INFO_OTROS_PLANES
    except Exception:
        pass
        
    return None


def _mask(value, *, visible: int = 4) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= visible:
        return "***"
    return f"***{text[-visible:]}"


def _coerce_state(value) -> ChatState | None:
    if isinstance(value, ChatState):
        return value
    if not value:
        return None
    try:
        return ChatState(value)
    except ValueError:
        return None


def _active_verification_context_state(
    current_state: ChatState,
    previous_state: str | ChatState | None,
) -> ChatState | None:
    if current_state in ACTIVE_VERIFICATION_STATES:
        return current_state

    previous = _coerce_state(previous_state)
    if (
        current_state in SERVICE_STATES_WITH_VERIFICATION_CONTEXT
        and previous in ACTIVE_VERIFICATION_STATES
    ):
        return previous

    return None


def _folio_input_from_text(
    text: str,
    current_state: ChatState,
    previous_state: str | ChatState | None = None,
) -> str | None:
    allow_bare = current_state in STATES_ALLOW_BARE_FOLIO
    if (
        not allow_bare
        and current_state in SERVICE_STATES_WITH_VERIFICATION_CONTEXT
        and _active_verification_context_state(current_state, previous_state)
    ):
        allow_bare = True

    return extraer_folio_si_mensaje_de_folio(
        text,
        allow_folio_suelto=allow_bare,
    )


def _cache_bridge_payload_for_folio(session, folio: str | None, bridge_verification=None) -> None:
    if not folio or not bridge_verification_found(bridge_verification):
        return
    try:
        upsert_cached_verification(
            session,
            str(folio),
            bridge_verification,
            raw=bridge_verification,
        )
    except Exception:
        logger.exception(
            "chatbot_bridge_cache_accept_failed",
            extra={
                "session_id": getattr(session, "id", None),
                "folio_masked": _mask(folio),
            },
        )


# --------------------------------------
# RESULT
# --------------------------------------

@dataclass
class FlowResult:
    reply: str
    next_state: ChatState
    buttons: list
    previous_state: str | None = None
    inconsistencia_patch: dict | None = None
    image_id: str | None = None


# --------------------------------------
# HELPERS
# --------------------------------------

def _try_mark_step(db, session, step_key: str, bridge_verification=None):
    if is_non_trackable_step(step_key):
        logger.debug("verification_step_not_trackable", extra={"step": step_key})
        return

    if not is_trackable_step(step_key):
        assert_valid_step(step_key)

    if not db:
        return

    folio = getattr(session, "folio", None)
    if not folio:
        return

    service = VerificationService(db)
    result = service.mark_step_from_folio(
        str(folio),
        step_key,
        1,
        phone=session.phone,
    )
    if result is None:
        no_cuenta = _no_cuenta_from_bridge(session, str(folio), bridge_verification)
        if no_cuenta:
            service.update_step_atomic(
                no_cuenta=no_cuenta,
                step=step_key,
                value=1,
                phone=session.phone,
            )

def is_descuento_query(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    exact_phrases = [
        "descuento por calificacion",
        "descuento por calificación",
        "descuento de estudiante",
        "descuento por estudiante",
        "descontar el pago inicial",
        "restar el pago inicial",
        "descontar mi enganche",
        "restar mi enganche",
        "descontar el enganche",
        "restar el enganche",
    ]

    if any(phrase in text for phrase in exact_phrases):
        return True

    # Búsqueda combinada: acción + objetivo
    has_action = any(w in text for w in ["descuento", "descontar", "descontado", "restar", "restado", "subsidio"])
    has_target = any(w in text for w in ["calificacion", "calificación", "estudiante", "pago inicial", "enganche", "promedio"])
    
    if has_action and has_target:
        return True

    return False

def is_devolucion_query(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    keywords = [
        "devolver",
        "devolucion",
        "quiero devolver",
        "quiero regresar la computadora"
        "cancelar compra",
        "regresar equipo",
        "ya no lo quiero",
    ]

    return any(k in text for k in keywords)


def _bridge_payload_for_folio(session, folio: str | None, bridge_verification=None):
    if bridge_verification_found(bridge_verification):
        return bridge_verification

    if not folio:
        return None

    cached_payload = get_cached_bridge_verification_payload(session, str(folio))
    if bridge_verification_found(cached_payload):
        return cached_payload

    return None


def _safe_render_current_state(current_state, session, db, previous_state=None) -> FlowResult | None:
    missing_fields = get_missing_render_fields(current_state, session, db)
    if not missing_fields:
        return None

    reply, buttons, image_id = render_state(current_state, session, db)
    return FlowResult(
        reply=reply,
        next_state=current_state,
        buttons=buttons,
        previous_state=previous_state,
        image_id=image_id,
    )


def _venta_or_bridge_for_folio(db, session, folio: str | None, bridge_verification=None):
    if not folio:
        return None

    venta = obtener_venta_por_folio(db, str(folio)) if db else None
    if venta:
        logger.info(
            "chatbot_folio_resolution_decision",
            extra={
                "folio_masked": _mask(folio),
                "found": True,
                "source": "local_db",
            },
        )
        return venta

    bridge_payload = _bridge_payload_for_folio(session, str(folio), bridge_verification)
    bridge_sale = bridge_sale_from_payload(bridge_payload)
    logger.info(
        "chatbot_folio_resolution_decision",
        extra={
            "folio_masked": _mask(folio),
            "found": bool(bridge_sale),
            "source": "siga_bridge" if bridge_sale else "not_found",
            "bridge_summary": bridge_sale_summary(bridge_payload) if bridge_payload else None,
        },
    )
    return bridge_sale


def _no_cuenta_from_bridge(session, folio: str | None, bridge_verification=None) -> str | None:
    bridge_payload = _bridge_payload_for_folio(session, folio, bridge_verification)
    bridge_sale = bridge_sale_from_payload(bridge_payload)
    no_cuenta = getattr(bridge_sale, "no_cuenta", None) if bridge_sale else None
    return str(no_cuenta) if no_cuenta else None


# --------------------------------------
# MAIN
# --------------------------------------

def process_message(
    session,
    text: str,
    intent: str | None = None,
    db=None,
    bridge_verification=None,
    is_media: bool = False,
) -> FlowResult:
    #logger.info(f"🟢 [Flujo] Inicio process_message | Estado: {session.state} | Intent: {intent} | Texto: '{text}'")

    # --------------------------------------
    # Si mandó folio para iniciar
    # --------------------------------------
    def _check_verification_complete(folio: str) -> FlowResult | None:    
        # 1. Intentar resolver el número de cuenta asociado al folio
        no_cuenta = (
            VerificationService(db).resolve_no_cuenta_from_folio(folio) if db else None
            or _no_cuenta_from_bridge(session, folio, bridge_verification)
        )
        
        # 2. Bloqueo si ya está finalizada en el historial (VerificacionCuenta)
        verificacion = obtener_verificacion_por_no_cuenta(db, no_cuenta) if db and no_cuenta else None
        
        if no_cuenta and verificacion:
            if verification_service.is_verification_complete(verificacion.json):
                menu_buttons = [
                    b for b in FLOW[ChatState.MENU_AYUDA].get("buttons", [])
                    if b.get("id") != "MENU_VERIFICACION"
                ]
                return FlowResult(
                    reply="✅ Esta cuenta ya fue verificada anteriormente.",
                    next_state=ChatState.FINALIZADO,
                    buttons=menu_buttons,
                    previous_state=None,
                )

        # 3. Bloqueo si otro teléfono ya lo está verificando en este momento (Simultáneo)
        if db and folio:
            from app.core.states.state_types import TERMINAL_STATES_FOR_LOCK
            
            # Buscamos otra sesión activa (no terminada) con el mismo folio
            other_session = (
                db.query(ChatSessions)
                .filter(
                    ChatSessions.folio == folio,
                    ChatSessions.phone != session.phone,
                    ChatSessions.state.notin_(TERMINAL_STATES_FOR_LOCK)
                )
                .first()
            )
            
            if other_session:
                phone_masked = f"***{other_session.phone[-4:]}" if other_session.phone else "desconocido"
                return FlowResult(
                    reply=f"⚠️ El folio *{folio}* ya está siendo verificado desde otro número de teléfono (terminación {phone_masked}).\n\nPor favor, espera a que termine o usa otro folio.",
                    next_state=ChatState.MENU_AYUDA,
                    buttons=FLOW[ChatState.MENU_AYUDA].get("buttons", []),
                    previous_state=None,
                )
    # --------------------------------------
    #  LOG FLOW EVENT (CLAVE)
    # --------------------------------------
    def _log(to_state_override=None, from_state_override=None):
        if db:
            try:
                log_from_state = from_state_override or current_state
                if to_state_override is None:
                    try:
                        log_to_state = next_state
                    except NameError:
                        return
                else:
                    log_to_state = to_state_override

                if not log_to_state:
                    return

                log_flow_event(
                    db=db,
                    session=session,
                    from_state=log_from_state.value if isinstance(log_from_state, ChatState) else log_from_state,
                    to_state=log_to_state.value if isinstance(log_to_state, ChatState) else log_to_state,
                    trigger_text=text if text else intent,
                    event_type="message" if text else "button",
                    detected_intent=detected_intent,
                    event_payload={
                        "buttons": [b.get("id") for b in (FLOW.get(log_to_state, {}).get("buttons", []))],
                    },
                )
            except Exception:
                pass

    from app.core.states.state_types import is_persistent_state, get_menu_ayuda_buttons, is_terminal_state

    current_state = ChatState(session.state)
    previous_state = session.previous_state

    # ==========================================
    # NORMALIZACIÓN DE ESTADOS DE RECORDATORIO
    # ==========================================
    # Si el usuario escribe algo (no importa qué) mientras hay un recordatorio pendiente,
    # lo tratamos como si ya hubiera reanudado el flujo original.
    REMINDER_STATES = [
        ChatState.RECORDATORIO, 
        ChatState.RECORDATORIO_1H, 
        ChatState.RECORDATORIO_2H, 
        ChatState.RECORDATORIO_24H
    ]
    if current_state in REMINDER_STATES and previous_state:
        # Solo normalizamos si el usuario no presionó explícitamente el botón "Continuar"
        if intent != "REANUDACION":
            current_state = ChatState(previous_state)
            # Sincronizamos con el modelo de sesión para que el resto del motor use el estado real
            session.state = current_state.value

    # Calcular el nuevo state_previous para preservar el punto de retorno
    if is_persistent_state(current_state):
        new_previous_state = current_state.value
    else:
        new_previous_state = previous_state

    # ==========================================
    # DETECCIÓN DE MENSAJE PREDETERMINADO DEL QR
    # ==========================================
    qr_text = text.strip() if text else ""
    if "quiero activar mis beneficios" in qr_text.lower() and "mi folio es" in qr_text.lower() and not re.search(r"\d", qr_text):
        session.folio = None
        _log(to_state_override=ChatState.CAMBIAR_FOLIO)
        return FlowResult(
            reply=messages.PEDIR_FOLIO,
            next_state=ChatState.CAMBIAR_FOLIO,
            buttons=[],
            previous_state=new_previous_state
        )


    # ==========================================
    # ESTADOS DE ESPERA Y ESCALAMIENTO (IGNORAR MENSAJES)
    # ==========================================
    escalation_states = {
        ChatState.ESPERANDO_REGISTRO,
        ChatState.LLAMADA,
        ChatState.ACLARACION,
        ChatState.DEVOLUCION_FINALIZADA,
        ChatState.COBRANZA_ESCALADO
    }
    if current_state in escalation_states:
        if current_state == ChatState.ESPERANDO_REGISTRO:
            # Si el usuario presionó el botón de cambiar folio (y es válido),
            # dejamos que pase de largo este bloque para que la validación
            # de botones más abajo lo procese correctamente.
            if intent == "CAMBIAR_FOLIO":
                pass
            else:
                # Check if user sent a folio directly in their text message
                direct_folio = extraer_folio_si_mensaje_de_folio(text, allow_folio_suelto=True)
                if direct_folio:
                    # Validate length of direct folio (must be >= 5 and <= 10)
                    if len(str(direct_folio)) < 5 or len(str(direct_folio)) > 10:
                        return FlowResult(
                            reply="⚠️ El folio ingresado no es válido. Por favor, verifícalo e inténtalo de nuevo.",
                            next_state=current_state,
                            buttons=[{"id": "CAMBIAR_FOLIO", "label": "🔄 Volver a intentar"}],
                            previous_state=previous_state
                        )

                    venta = _venta_or_bridge_for_folio(db, session, direct_folio, bridge_verification)
                    if venta:
                        # Folio exists! Proceed/advance
                        target_state = ChatState.INICIO2
                        
                        verification_result = _check_verification_complete(direct_folio)
                        if verification_result:
                            return verification_result
                        
                        reset_verification_context_for_folio(session, direct_folio)
                        _cache_bridge_payload_for_folio(session, direct_folio, bridge_verification)

                        _log(to_state_override=target_state)

                        reply_state, buttons, image_id = render_state(target_state, session, db)
                        return FlowResult(
                            reply=reply_state,
                            next_state=target_state,
                            buttons=buttons,
                            image_id=image_id,
                            previous_state=previous_state
                        )
                    else:
                        # Folio does not exist! Stay in ESPERANDO_REGISTRO but with the new folio
                        reset_verification_context_for_folio(session, direct_folio)
                        _log(to_state_override=ChatState.ESPERANDO_REGISTRO)
                        
                        mensaje_saludo = messages.SALA_ESPERA.format(folio=direct_folio)
                        return FlowResult(
                            reply=mensaje_saludo,
                            next_state=ChatState.ESPERANDO_REGISTRO,
                            buttons=[{"id": "CAMBIAR_FOLIO", "label": "✏️ Cambiar folio"}],
                            previous_state=previous_state
                        )
                
                # El sistema está esperando a que el webhook externo cambie el estado
                # o que un asesor humano atienda la conversación.
                # Ignoramos cualquier mensaje del usuario para no romper el flujo ni interrumpir.
                return FlowResult(
                    reply=None,
                    next_state=current_state,
                    buttons=[],
                    previous_state=previous_state
                )
        else:
            # Para los demás estados de escalamiento, simplemente ignorar todo
            return FlowResult(
                reply=None,
                next_state=current_state,
                buttons=[],
                previous_state=previous_state
            )

    # ==========================================
    # VALIDACIÓN DEL RETO DE SEGURIDAD
    # ==========================================
#     if current_state == ChatState.RETO_SEGURIDAD:
#         venta = obtener_venta_por_folio(db, session.folio)
# 
#         # Si por alguna razón la venta desapareció de la BD
#         if not venta or not venta.nombre_completo:
#             return FlowResult(
#                 reply="Hubo un problema recuperando los datos del folio. Un asesor te contactará a la brevedad.",
#                 next_state=ChatState.ACLARACION,
#                 buttons=[],
#                 previous_state=new_previous_state
#             )
# 
#         import unicodedata
#         
#         # Función interna para limpiar acentos y mayúsculas
#         def clean_text(txt):
#             if not txt: return ""
#             txt = txt.lower().strip()
#             return unicodedata.normalize('NFKD', txt).encode('ASCII', 'ignore').decode('utf-8')
# 
#         # Extraemos el primer nombre real del sistema (ej. "Juan Pablo" -> "Juan")
#         nombre_completo_real = venta.nombre_completo.strip()
#         primer_nombre_real = nombre_completo_real.split(" ")[0]
#         primer_nombre_limpio = clean_text(primer_nombre_real)
# 
#         texto_usuario_limpio = clean_text(text)
# 
#         # Validación: El primer nombre real debe estar contenido en la respuesta del usuario.
#         # Esto permite que "Carlos" haga match con "Soy Carlos" o "cárlos"
#         if primer_nombre_limpio in texto_usuario_limpio:
#             # ÉXITO: Levantamos el muro, reiniciamos contador y pasamos a confirmar
#             session.invalid_folio_attempts = 0
#             _log()
#             
#             reply_state, botones, _ = render_state(ChatState.CONFIRMAR_NOMBRE, session, db)
#             reply = f"{messages.RETO_SEGURIDAD_EXITO}\n\n{reply_state}"
#             
#             return FlowResult(
#                 reply=reply,
#                 next_state=ChatState.CONFIRMAR_NOMBRE,
#                 buttons=botones,
#                 previous_state=new_previous_state
#             )
#         else:
#             # FALLO: Sumamos un error al contador
#             session.invalid_folio_attempts = (session.invalid_folio_attempts or 0) + 1
#             intentos_restantes = 3 - session.invalid_folio_attempts
# 
#             if intentos_restantes > 0:
#                 # Le damos otra oportunidad
#                 reply = messages.RETO_SEGURIDAD_FALLO.format(intentos_restantes=intentos_restantes)
#                 return FlowResult(
#                     reply=reply,
#                     next_state=ChatState.RETO_SEGURIDAD,
#                     buttons=[],
#                     previous_state=new_previous_state
#                 )
#             else:
#                 # BLOQUEO DEFINITIVO
#                 reply = messages.RETO_SEGURIDAD_BLOQUEO
#                 
#                 # Derivamos a llamada para proteger la información
#                 return FlowResult(
#                     reply=reply,
#                     next_state=ChatState.LLAMADA, 
#                     buttons=[],
#                     previous_state=new_previous_state
#                 )
# 
    # --------------------------------------
    # 1. Detectar intención (con fallback IA)
    # --------------------------------------

    folio = None

    if intent and intent.isupper():
        # VALIDAR QUE EL BOTÓN PERTENECE AL ESTADO ACTUAL
        valid_button_ids = [b.get("id") for b in FLOW.get(current_state, {}).get("buttons", [])]
        
        if current_state == ChatState.COMPONENTES_FALTANTES:
            from app.core.states.state_handlers import COMPONENTES_MAP
            for k in COMPONENTES_MAP.keys():
                valid_button_ids.append(k)
        
        if current_state in [ChatState.MENU_AYUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO, ChatState.FINALIZADO]:
            menu_btns = get_menu_ayuda_buttons(new_previous_state)
            valid_button_ids.extend([b.get("id") for b in menu_btns])
            
        if current_state == ChatState.SELECCIONAR_FOLIO and intent.startswith("SELECCIONAR_FOLIO_"):
            valid_button_ids.append(intent)

        # CAMBIAR_FOLIO se envía dinámicamente por las validaciones de folio
        # (folio inválido, solo letras, etc.) — aceptarlo solo en esos estados
        folio_states_with_retry = {
            ChatState.ESPERA, ChatState.CAMBIAR_FOLIO,
            ChatState.CAMBIAR_FOLIO_DEVOLUCION, ChatState.CAMBIAR_FOLIO_DESCUENTO,
            ChatState.INICIO, ChatState.ESPERANDO_REGISTRO,
        }
        if current_state in folio_states_with_retry and intent == "CAMBIAR_FOLIO":
            valid_button_ids.append("CAMBIAR_FOLIO")
            
        if intent not in valid_button_ids:
            logger.info(f"Botón obsoleto ignorado: {intent} (estado actual: {current_state})")
            if current_state == ChatState.INFO_COMPROBANTE_ACCESO:
                reply, buttons, image_id = render_state(current_state, session, db)
                return FlowResult(
                    reply=reply,
                    next_state=current_state,
                    buttons=buttons,
                    previous_state=new_previous_state,
                    image_id=image_id,
                )
            return FlowResult(
                reply=None,
                next_state=current_state,
                buttons=[],
                previous_state=new_previous_state
            )

        # Si CAMBIAR_FOLIO pasó la validación, pedir folio de nuevo
        if intent == "CAMBIAR_FOLIO":
            session.folio = None
            _log(to_state_override=ChatState.CAMBIAR_FOLIO)
            return FlowResult(
                reply=messages.PEDIR_FOLIO,
                next_state=ChatState.CAMBIAR_FOLIO,
                buttons=[],
                previous_state=previous_state
            )

        detected_intent = intent
        action = "advance"
    else:
        if current_state == ChatState.COBRANZA:
            if is_media:
                return FlowResult(
                    reply="Recibimos tu comprobante o archivo. Lo revisaremos a la brevedad y te daremos respuesta.",
                    next_state=ChatState.COBRANZA_ESCALADO,
                    buttons=[],
                    previous_state=previous_state
                )
                
            text_lower = text.strip().lower()
            if text_lower == "tengo una duda":
                return FlowResult(
                    reply=None,
                    next_state=ChatState.COBRANZA_DUDA,
                    buttons=[],
                    previous_state=previous_state
                )
            else:
                return FlowResult(
                    reply=None,
                    next_state=ChatState.COBRANZA_ESCALADO,
                    buttons=[],
                    previous_state=previous_state
                )

        if current_state == ChatState.COBRANZA_DUDA:
            if is_media:
                reply_text = "Recibimos tu comprobante o archivo. Lo revisaremos a la brevedad y te daremos respuesta."
            else:
                reply_text = None # usa el default de COBRANZA_ESCALADO
                
            return FlowResult(
                reply=reply_text,
                next_state=ChatState.COBRANZA_ESCALADO,
                buttons=[],
                previous_state=previous_state
            )

        # --------------------------------------
        # Manejo de imágenes no esperadas en verificación activa
        # --------------------------------------
        from app.core.states.state_types import is_persistent_state, is_terminal_state
        if is_media and current_state != ChatState.VERIFICAR_FOTO_COMPONENTE:
            if is_persistent_state(current_state) and not is_terminal_state(current_state):
                return FlowResult(
                    reply="Recibí tu archivo o comprobante, no olvides terminar tu verificación.",
                    next_state=ChatState.MENU_AYUDA,
                    buttons=[
                        {"id": "MENU_VERIFICACION", "label": "📄 Ir a verificación"}
                    ],
                    previous_state=current_state.value
                )

        # --------------------------------------
        # 1. Detectar intención (con prioridad)
        # --------------------------------------
        text_clean = text.strip().lower()

        def clean_for_match(txt):
            txt = txt.lower()
            normalized = unicodedata.normalize('NFKD', txt).encode('ASCII', 'ignore').decode('utf-8')
            return re.sub(r'[^a-z0-9\s]', '', normalized).strip()

        text_norm = clean_for_match(text_clean)
        information_confirmation_matched = False

        def is_information_confirmation(txt):
            if not txt:
                return False

            exact_confirmations = {
                "no",
                "no gracias",
                "no tengo duda",
                "no tengo dudas",
                "no hay duda",
                "no hay dudas",
                "ninguna",
                "ninguna duda",
                "ninguna duda gracias",
                "sin duda",
                "sin dudas",
                "todo claro",
                "esta claro",
                "quedo claro",
                "me queda claro",
                "entendido",
            }
            if txt in exact_confirmations:
                return True

            no_doubt_markers = ("no tengo", "no hay", "ninguna", "ningun", "sin")
            if any(marker in txt for marker in no_doubt_markers) and (
                "duda" in txt or "pregunta" in txt
            ):
                return True

            clarity_markers = ("todo claro", "esta claro", "quedo claro", "me queda claro")
            return any(marker in txt for marker in clarity_markers)
        
        button_matched = False
        state_buttons = list(FLOW.get(current_state, {}).get("buttons", []))
        
        if current_state == ChatState.COMPONENTES_FALTANTES:
            from app.core.states.state_handlers import COMPONENTES_MAP
            for k, v in COMPONENTES_MAP.items():
                state_buttons.append({"id": k, "label": v["label"]})
                for alias in v.get("aliases", []):
                    state_buttons.append({"id": k, "label": alias})
        
        duda_keywords_exact = {
            "tengo una duda", "tengo duda", "tengo dudas", "una duda", 
            "una pregunta", "tengo una pregunta", "pregunta", "duda", 
            "hacer una pregunta", "quiero hacer una pregunta", "tengo preguntas",
            "1 duda", "1 pregunta", "tengo 1 duda", "tengo 1 pregunta",
            "tengo otra duda", "otra duda", "otra pregunta", "tengo otra pregunta"
        }
        es_duda_corta = text_norm in duda_keywords_exact

        for btn in state_buttons:
            # quitar emojis comunes y limpiar
            label_clean = btn["label"].replace('✅', '').replace('❓', '').replace('📄', '').replace('❌', '').replace('▶️', '')
            label_norm = clean_for_match(label_clean)
            
            # Match exacto o casi exacto
            if text_norm == label_norm or text_norm == label_norm.rstrip('s') or text_norm.rstrip('s') == label_norm:
                detected_intent = btn["id"]
                action = "advance"
                folio = None
                button_matched = True
                break
            # Inclusión (para frases más largas, ej. "tengo duda" dentro de "tengo dudas")
            elif len(text_norm) >= 4 and text_norm in label_norm:
                detected_intent = btn["id"]
                action = "advance"
                folio = None
                button_matched = True
                break
            # Mapeo a botones equivalentes si el texto es una de las frases cortas comunes evaluadas
            elif es_duda_corta and ("duda" in label_norm or "pregunta" in label_norm):
                detected_intent = btn["id"]
                action = "advance"
                folio = None
                button_matched = True
                break

        if not button_matched:
            # --- Atajos adicionales manuales ---
            if current_state == ChatState.MENU_AYUDA and "pregunta" in text_clean:
                detected_intent = "MENU_DUDA"
                action = "advance"
                folio = None
            elif current_state in (ChatState.MENU_AYUDA, ChatState.FINALIZADO) and text_norm in {
                "verificacion", "ir a verificacion", "verificar", "quiero verificar",
                "continuar verificacion", "iniciar verificacion", "empezar verificacion"
            }:
                # Solo disparar MENU_VERIFICACION si el mensaje es exactamente una de las frases conocidas
                # para evitar que frases como "no quiero la verificacion" o preguntas lo activen.
                detected_intent = "MENU_VERIFICACION"
                action = "advance"
                folio = None
            else:
                detected_intent, folio = detect_intent(text, current_state)

                # detectar duda explícita si detect_intent no fue crítico
                if is_doubt(text) and detected_intent not in ("human", "call", "start_verification"):
                    detected_intent = "doubt"

        if get_state_type(current_state) == "information" and is_information_confirmation(text_norm):
            detected_intent = "affirmative"
            information_confirmation_matched = True

        # --------------------------------------
        # HARD RULES (máxima prioridad)
        # --------------------------------------
        state_type = get_state_type(current_state)

        if text_clean in {"si", "sí"}:
            detected_intent = "affirmative"

        elif text_clean == "no":
            # interpretar según contexto del estado
            if state_type == "confirmation":
                detected_intent = "negative"   # inconsistencia
            elif state_type == "information":
                detected_intent = "affirmative"  # no tiene dudas
                information_confirmation_matched = True
            else:
                detected_intent = "negative"

        # --------------------------------------
        # DEFINIR INTENTS PROTEGIDOS
        # --------------------------------------

        PROTECTED_INTENTS = {
            "affirmative",
            "negative",
            "call",
            "human",
            "later",
            "start_verification"
        }

        # --------------------------------------
        # DECIDIR SI IA DEBE INTERVENIR
        # --------------------------------------

        context_temp = ConversationContext(
            state=current_state,
            previous_state=previous_state,
            text=text,
            intent=detected_intent,
            phone=session.phone,
            folio=session.folio,
            venta=None,
            bridge_verification=bridge_verification,
            session=session,
            db=db
        )

        state_type = get_state_type(current_state)

        # decidir uso de IA según estado
        if state_type == "confirmation":
            use_ai = len(text.split()) >= 2  # Permitir IA si parece una corrección o detalle

        elif state_type == "information":
            use_ai = not information_confirmation_matched

        elif state_type == "acknowledgement":
            use_ai = False

        elif state_type == "inconsistency":
            use_ai = True   # siempre usar IA

        else:
            use_ai = should_use_ai(text, detected_intent, current_state)

        # CASO 1: intent débil → IA decide
        if detected_intent in ("other", "ambiguous", None) and use_ai:

            ai_result = interpret_intent_with_ai(
                text,
                context_temp,
                session=session
            )

            if ai_result:
                ai_intent = ai_result.get("intent")
                confidence = ai_result.get("confidence", "low")

                if ai_intent and confidence in ("medium", "high"):
                    logger.info(f"🤖 IA fallback → {ai_intent} ({confidence})")
                    detected_intent = ai_intent

        # CASO 2: intent válido PERO mensaje complejo → IA puede reinterpretar
        # EXCEPCIÓN: "start_verification" es determinístico (extraído por regex del folio)
        # y nunca debe ser sobreescrito por la IA, ya que ni siquiera está en VALID_INTENTS.
        elif detected_intent in PROTECTED_INTENTS and use_ai and detected_intent != "start_verification":

            ai_result = interpret_intent_with_ai(
                text,
                context_temp,
                session=session
            )

            if ai_result:
                ai_intent = ai_result.get("intent")
                confidence = ai_result.get("confidence", "low")

                # SOLO si IA tiene alta confianza
                if ai_intent and confidence in ("medium", "high"):
                    logger.info(f"🤖 IA override → {ai_intent} ({confidence})")
                    detected_intent = ai_intent

        # --------------------------------------
        # ROUTING NORMAL
        # --------------------------------------

        if not button_matched:
            action = route_intent(current_state, detected_intent)
            #logger.info(f"🔀 [Router] Estado: {current_state.value} | Intent Final: {detected_intent} -> Acción: {action}")

        # ==========================================
        # INTERCEPCIÓN DE DUDAS (JUMP-AHEAD A PREGUNTAS INFO_)
        # ==========================================
        if (detected_intent == "doubt" or action == "ai_doubt") and not (intent and intent.isupper()):
            jump_state = _classify_doubt_to_info_state(text)

            # Evitar saltar a la misma pregunta de información actual o previa (previene loops)
            if jump_state and jump_state == current_state:
                jump_state = None
            if jump_state and session.previous_state and jump_state.value == session.previous_state:
                jump_state = None

            if jump_state:
                # Determinar punto de retorno
                if session.extra_json and "verification_suspended_state" in session.extra_json:
                    suspended_state_val = session.extra_json["verification_suspended_state"]
                elif current_state in {ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.FUERA_DE_FLUJO, ChatState.ESPERA}:
                    suspended_state_val = session.previous_state or ChatState.INICIO2.value
                else:
                    suspended_state_val = current_state.value

                from app.core.verification.verification_schema import VERIFICATION_STEP_ORDER
                from app.services.verification_tracker import STEP_MAP

                suspended_step = STEP_MAP.get(ChatState(suspended_state_val))
                jump_step = STEP_MAP.get(jump_state)

                # Validar que sea un paso posterior para calificar como jump-ahead
                if (suspended_step in VERIFICATION_STEP_ORDER and jump_step in VERIFICATION_STEP_ORDER 
                    and VERIFICATION_STEP_ORDER.index(jump_step) > VERIFICATION_STEP_ORDER.index(suspended_step)):
                    
                    # 1. Guardar estado suspendido
                    new_extra = dict(session.extra_json or {})
                    new_extra["verification_suspended_state"] = suspended_state_val
                    session.extra_json = new_extra
                    
                    # 2. Transicionar estado
                    session.state = jump_state.value
                    session.previous_state = suspended_state_val
                    
                    # 3. Renderizar el estado de información como respuesta
                    reply_state, buttons, image_id = render_state(jump_state, session, db)
                    
                    _log(to_state_override=jump_state, from_state_override=current_state)
                    
                    return FlowResult(
                        reply=reply_state,
                        next_state=jump_state,
                        buttons=buttons,
                        previous_state=suspended_state_val,
                        image_id=image_id
                    )

    # ==========================================
    # DETECTAR SI TIENE VERIFICACIÓN ACTIVA Y TRATA DE CAMBIAR DE FOLIO
    # ==========================================
    active_context_state = _active_verification_context_state(current_state, previous_state)
    folio_detectado = _folio_input_from_text(text, current_state, previous_state)
    folio_intento = folio_detectado or folio
    detected_folio_is_new = bool(folio_intento and str(folio_intento) != str(session.folio))

    if session.folio and active_context_state:
        if detected_folio_is_new:
            next_state = ChatState.MENU_AYUDA
            _log()
            return FlowResult(
                reply=messages.VERIFICACION_ACTIVA,
                next_state=ChatState.MENU_AYUDA,
                buttons=[
                    {"id": "MENU_VERIFICACION", "label": "📄 Ir a verificación"},
                    {"id": "MENU_DUDA", "label": "❓ Hacer una pregunta"},
                ],
                previous_state=active_context_state.value
            )
        elif folio_intento and str(folio_intento) == str(session.folio):
            # Mismo folio ingresado de nuevo en medio de verificación activa
            # Simplemente le recordamos y volvemos a renderizar la pregunta actual del estado
            reply_state, buttons, image_id = render_state(active_context_state, session, db)
            reply = f"{messages.VERIFICACION_MISMO_FOLIO}\n\n{reply_state}"
            next_state = active_context_state
            _log()
            return FlowResult(
                reply=reply,
                next_state=active_context_state,
                buttons=buttons,
                image_id=image_id,
                previous_state=previous_state
            )

    # --------------------------------------
    # 2. Detectar folio automático
    # --------------------------------------

    folio_detectado = _folio_input_from_text(text, current_state, previous_state)

    current_folio = str(getattr(session, "folio", None) or "")
    detected_folio_is_new = bool(folio_detectado and str(folio_detectado) != current_folio)

    if folio_detectado and (not session.folio or detected_folio_is_new) and current_state in STATES_ALLOW_AUTO_FOLIO:
        if len(str(folio_detectado)) < 5 or len(str(folio_detectado)) > 10:
            return FlowResult(
                reply="⚠️ El folio ingresado no es válido. Por favor, verifícalo e inténtalo de nuevo.",
                next_state=current_state,
                buttons=[{"id": "CAMBIAR_FOLIO", "label": "🔄 Volver a intentar"}],
                previous_state=previous_state
            )

        venta = _venta_or_bridge_for_folio(db, session, folio_detectado, bridge_verification)

        if venta:
            target_state = ChatState.INICIO2
            if current_state == ChatState.CAMBIAR_FOLIO_DEVOLUCION:
                target_state = ChatState.CONFIRMAR_FOLIO_DEVOLUCION
            elif current_state == ChatState.CAMBIAR_FOLIO_DESCUENTO:
                target_state = ChatState.CONFIRMAR_FOLIO_DESCUENTO
            
            verification_result = _check_verification_complete(folio_detectado)

            if verification_result:
                return verification_result
            
            reset_verification_context_for_folio(session, folio_detectado)
            _cache_bridge_payload_for_folio(session, folio_detectado, bridge_verification)

            _log()

            reply_state, buttons, image_id = render_state(target_state, session, db)
            
            return FlowResult(
                reply=reply_state,
                next_state=target_state,
                buttons=buttons,
                image_id=image_id
            )

    # --------------------------------------
    # 2.5 Validación de letras en estados de folio
    # --------------------------------------

    estados_folio = {ChatState.CAMBIAR_FOLIO, ChatState.CAMBIAR_FOLIO_DEVOLUCION, ChatState.CAMBIAR_FOLIO_DESCUENTO, ChatState.INICIO}
    
    if current_state in estados_folio and not folio_detectado and not button_matched and detected_intent != "start_verification":
        if text and not re.search(r"\d", text) and detected_intent in ("other", "ambiguous", None, "greeting"):
            return FlowResult(
                reply="⚠️ Parece que ingresaste solo letras. Recuerda que el folio es un código numérico. Por favor, intenta de nuevo escribiendo solo los números de tu folio.",
                next_state=current_state,
                buttons=[{"id": "CAMBIAR_FOLIO", "label": "🔄 Volver a intentar"}],
                previous_state=previous_state
            )

    # --------------------------------------
    # 3. Menú fuera de flujo
    # --------------------------------------

    if current_state in [ChatState.ESPERA, ChatState.FUERA_DE_FLUJO] and action != "advance" and detected_intent != "start_verification":
        #logger.info(f"⏭️ [Flujo] Redirigiendo a MENU_AYUDA (estado: {current_state.value}, sin avance).")
        return FlowResult(
            reply=messages.MENU_AYUDA,
            next_state=ChatState.MENU_AYUDA,
            buttons=get_menu_ayuda_buttons(new_previous_state)
        )

    # --------------------------------------
    # 4. Inicio verificación
    # --------------------------------------

    if detected_intent == "start_verification":
        folio_a_buscar = folio_detectado if folio_detectado else folio
        
        if not folio_a_buscar:
            return FlowResult(
                reply=messages.PEDIR_FOLIO_INICIO,
                next_state=ChatState.CAMBIAR_FOLIO,
                buttons=[],
                previous_state=new_previous_state
            )

        if len(str(folio_a_buscar)) < 5 or len(str(folio_a_buscar)) > 10:
            next_state_for_invalid = ChatState.CAMBIAR_FOLIO if current_state == ChatState.INICIO else current_state
            return FlowResult(
                reply="⚠️ El folio ingresado no es válido. Por favor, verifícalo e inténtalo de nuevo.",
                next_state=next_state_for_invalid,
                buttons=[{"id": "CAMBIAR_FOLIO", "label": "🔄 Volver a intentar"}],
                previous_state=new_previous_state
            )

        venta = _venta_or_bridge_for_folio(db, session, folio_a_buscar, bridge_verification)

        if not venta:
            # ==========================================
            # FASE 1: SALA DE ESPERA (El folio no existe AÚN)
            # Guardamos el folio en sesión y ponemos en pausa.
            # ==========================================
            reset_verification_context_for_folio(session, folio_a_buscar)
            _log()
            
            mensaje_saludo = messages.SALA_ESPERA.format(folio=folio_a_buscar)
            
            return FlowResult(
                reply=mensaje_saludo,
                next_state=ChatState.ESPERANDO_REGISTRO,
                buttons=[{"id": "CAMBIAR_FOLIO", "label": "✏️ Cambiar folio"}],
                previous_state=new_previous_state
            )
        
        # ==========================================
        # Si la venta SÍ existe, continuamos normal...
        # ==========================================
        verification_result = _check_verification_complete(folio_a_buscar)

        if verification_result:
            return verification_result

        reset_verification_context_for_folio(session, folio_a_buscar)
        _cache_bridge_payload_for_folio(session, folio_a_buscar, bridge_verification)

        _try_mark_step(db, session, "inicio", bridge_verification)
        _try_mark_step(db, session, "folio", bridge_verification)

        _log()

        reply_state, buttons, _ = render_state(ChatState.INICIO2, session, db)
        
        return FlowResult(
            reply=reply_state,
            next_state=ChatState.INICIO2,
            buttons=buttons
        )

    # --------------------------------------
    # 5. Contexto
    # --------------------------------------

    blocked_render = _safe_render_current_state(current_state, session, db, new_previous_state)
    if blocked_render:
        logger.info(
            "verification_continuation_blocked_missing_snapshot",
            extra={
                "session_id": getattr(session, "id", None),
                "state": current_state.value,
                "folio_masked": _mask(getattr(session, "folio", None)),
            },
        )
        return blocked_render

    venta = _venta_or_bridge_for_folio(db, session, session.folio, bridge_verification) if session.folio else None

    context = ConversationContext(
        state=current_state,
        previous_state=previous_state,
        text=text,
        intent=detected_intent,
        phone=session.phone,
        folio=session.folio,
        venta=venta,
        bridge_verification=bridge_verification,
        session=session,
        db=db
    )

    # --------------------------------------
    # PROCESAR INCONSISTENCIA (IA)
    # --------------------------------------

    is_direct_inconsistency = (
        get_state_type(current_state) == "confirmation" and
        current_state != ChatState.CONFIRMAR_COMPONENTES and
        detected_intent == "negative" and
        len(text.split()) > 2
    )

    if current_state == ChatState.INCONSISTENCIA or is_direct_inconsistency:

        result = analyze_inconsistency(text, context, session=session)
        severidad = result["severidad"]

        # --------------------------------------
        # CONTAR PRIMERO (leer estado actual)
        # --------------------------------------

        # Leer contador actual de DB antes de guardar
        inc_actual = open_or_patch_inconsistencia(
            db=db,
            phone=session.phone,
            folio=session.folio,
            session_id=session.id,
            patch={}
        )

        extra = inc_actual.extra_json or {}
        contador = extra.get("contador", {
            "leve": 0,
            "moderada": 0,
            "critica": 0,
            "total": 0,
        })

        if severidad in contador:
            contador[severidad] += 1
        contador["total"] += 1

        moderadas_efectivas = contador["moderada"] + (contador["leve"] // 2)

        # --------------------------------------
        # GUARDAR INCONSISTENCIA + CONTADOR
        # --------------------------------------

        entrada = {
            "estado_origen": result["estado_origen"],
            "mensaje_cliente": result["mensaje_cliente"],
            "severidad": severidad,
        }

        # Reconstruir contador con el orden correcto explícito
        contador_ordenado = {
            "leve":     contador["leve"],
            "moderada": contador["moderada"],
            "critica":  contador["critica"],
            "total":    contador["total"],
        }

        open_or_patch_inconsistencia(
            db=db,
            phone=session.phone,
            folio=session.folio,
            session_id=session.id,
            patch={
                "inconsistencias_append": [entrada],
                "contador": contador_ordenado,
            }
        )

        # --------------------------------------
        # DECISIÓN
        # --------------------------------------

        logger.debug(
            "inconsistency_ai_classified",
            extra={
                "session_id": getattr(session, "id", None),
                "severity": severidad,
                "total": contador.get("total"),
                "moderadas_efectivas": moderadas_efectivas,
            },
        )

        # 🔴 crítica → parar flujo
        if severidad == "critica":
            return FlowResult(
                reply=messages.ESCALAMIENTO_CRITICO,
                next_state=ChatState.ACLARACION,
                buttons=[],
                previous_state=new_previous_state
            )

        # 🟡 demasiadas inconsistencias → parar flujo
        if moderadas_efectivas > 2 or contador["total"] > 3:
            return FlowResult(
                reply=messages.ESCALAMIENTO_MULTIPLES,
                next_state=ChatState.ACLARACION,
                buttons=[],
                previous_state=new_previous_state
            )

        # 🟢 continuar flujo
        from app.core.flow.flow import NEXT_STATE_MAP

        origen_inco = previous_state if current_state == ChatState.INCONSISTENCIA else current_state
        prev = ChatState(origen_inco) if origen_inco else None
        next_state = NEXT_STATE_MAP.get(prev) or prev or ChatState.INICIO

        next_state = handle_flow_skips(context, next_state)

        reply_state, buttons, image_id = render_state(next_state, session, db)
        reply = f"{messages.CORRECCION_REGISTRADA}\n\n{reply_state}" if reply_state else messages.CORRECCION_REGISTRADA

        _log()

        return FlowResult(
            reply=reply,
            next_state=next_state,
            buttons=buttons,
            previous_state=new_previous_state,
            image_id=image_id,
        )


    # --------------------------------------
    # 6. HANDLERS ESPECIALES
    # --------------------------------------

    special = handle_special_cases(context)

    if special:
        special_state = special.get("state")
        _log(special_state)
        #logger.info(f"✨ [Flujo] Caso especial manejado → Siguiente estado: {special_state.value if hasattr(special_state, 'value') else special_state}")

        return FlowResult(
            reply=special.get("reply"),
            next_state=special_state,
            buttons=special.get("buttons", []),
            previous_state=new_previous_state,
            inconsistencia_patch=special.get("patch"),
            image_id=special.get("image_id"),
        )

    # --------------------------------------
    # 7. ACCIONES DIRECTAS (ESCALAMIENTO)
    # --------------------------------------

    if action == "escalate":
        _log(ChatState.LLAMADA)
        return FlowResult(
            reply=messages.ACLARACION,
            next_state=ChatState.LLAMADA,
            buttons=FLOW[ChatState.LLAMADA].get("buttons", []),
            previous_state=new_previous_state
        )

    if action == "escalate_call":
        _log(ChatState.LLAMADA)
        return FlowResult(
            reply=messages.ACLARACION,
            next_state=ChatState.LLAMADA,
            buttons=FLOW[ChatState.LLAMADA].get("buttons", []),
            previous_state=new_previous_state
        )
    
    # --------------------------------------
    # DESGLOSE DE DESCUENTO 
    # --------------------------------------

    if is_descuento_query(text) or detected_intent == "descuento":

        if not session.folio:
            return FlowResult(
                reply=messages.PEDIR_FOLIO_DESCUENTO,
                next_state=ChatState.CAMBIAR_FOLIO_DESCUENTO,
                buttons=[],
                previous_state=new_previous_state
            )

        venta = _venta_or_bridge_for_folio(db, session, session.folio, bridge_verification)

        if venta:
            desglose = MessageBuilder.build_descuento_desglose(venta)

            current_state = ChatState(session.state)
            original_state_for_previous = current_state

            is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

            if is_finished:
                current_state = ChatState.FINALIZADO
                reply = f"{desglose}\n\n{messages.EN_QUE_MAS_AYUDAR}"
                image_id = None
                buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
            else:
                current_state = ChatState.MENU_AYUDA
                reply = f"{desglose}\n\n{messages.EN_QUE_MAS_AYUDAR}"
                buttons = get_menu_ayuda_buttons(new_previous_state)
                image_id = None

            # Preservar el state original como previous_state para poder regresar a la verificación
            if original_state_for_previous in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]:
                saved_previous = session.previous_state
            else:
                saved_previous = session.state

            return FlowResult(
                reply=reply,
                next_state=current_state,
                buttons=buttons,
                previous_state=saved_previous,
                image_id=image_id
            )
        
    # --------------------------------------
    # DEVOLUCIÓN (INICIO FLUJO)
    # --------------------------------------

    if is_devolucion_query(text) or detected_intent == "devolucion":

        if not session.folio:
            return FlowResult(
                reply=messages.PEDIR_FOLIO_DEVOLUCION,
                next_state=ChatState.CAMBIAR_FOLIO_DEVOLUCION,
                buttons=[],
                previous_state=new_previous_state
            )
        


        return FlowResult(
            reply=MessageBuilder.build_devolucion_confirmacion(),
            next_state=ChatState.DEVOLUCION_CONFIRMAR,
            buttons=FLOW.get(ChatState.DEVOLUCION_CONFIRMAR, {}).get("buttons", []),
            previous_state=new_previous_state
        )
    
    # --------------------------------------
    # 8. IA (CONTROLADA POR TIPO)
    # --------------------------------------

    # --------------------------------------
    # FAQ (RESPUESTA DIRECTA SIN IA)
    # --------------------------------------

    faq_response, faq_image_id = find_faq_answer(
        text,
        context.venta,
        session=session,
        bridge_verification=bridge_verification,
    )

    if faq_response:
        current_state = ChatState(session.state)
        # Capturamos el estado original ANTES de cualquier reasignación
        original_state_for_previous = current_state

        reply_state, buttons, image_id = render_state(
            current_state,
            session,
            db
        )

        # Estados donde NO queremos concatenar la pregunta de verificación:
        # - estados no-verificación (menú, duda, fuera de flujo...)
        # - estados de INFORMACIÓN: el mensaje ya es largo, mostramos solo el menú
        is_info_state = get_state_type(current_state) == "information"
        skip_verification_append = (
            current_state in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA,
                              ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]
            or is_info_state
        )

        is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

        if is_finished:
            current_state = ChatState.FINALIZADO
            reply = f"{faq_response}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            image_id = faq_image_id
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif not skip_verification_append and reply_state:
            reply = f"{faq_response}\n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
            image_id = faq_image_id or image_id
        else:
            #logger.info(f"⏭️ [Flujo] Redirigiendo a MENU_AYUDA (FAQ en estado {original_state_for_previous.value}).")
            current_state = ChatState.MENU_AYUDA
            reply = f"{faq_response}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            buttons = get_menu_ayuda_buttons(new_previous_state)
            image_id = faq_image_id

        # Si veníamos de DUDA/MENU_DUDA, preservar el previous_state de la sesión
        # Si veníamos de un estado de información directamente, también lo guardamos
        # como previous_state para que "Ir a verificación" regrese al lugar correcto.
        if original_state_for_previous in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]:
            saved_previous = session.previous_state
        else:
            saved_previous = session.state 

        _log()
         

        return FlowResult(
            reply=reply,
            next_state=current_state,
            buttons=buttons,
            previous_state=saved_previous,
            image_id=image_id
        )
    # --------------------------------------
    # SALUDOS GENÉRICOS (SIN IA)
    # --------------------------------------
    if action == "greeting" and not (intent and intent.isupper()):
        
        # Como ya normalizamos al inicio, current_state ya tiene la pregunta correcta
        current_state = ChatState(session.state)
        
        # Capturamos el estado original ANTES de cualquier reasignación a MENU_AYUDA o FINALIZADO
        original_state_for_previous = current_state
        reply_state, buttons, image_id = render_state(current_state, session, db)

        is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

        if is_finished:
            current_state = ChatState.FINALIZADO
            reply = f"👋🏻 ¡Hola!\n\n{messages.EN_QUE_MAS_AYUDAR}"
            image_id = None
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif current_state not in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO] and reply_state:
            reply = f"👋🏻 ¡Hola! \n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
        else:
            current_state = ChatState.MENU_AYUDA
            reply = f"👋🏻 ¡Hola! \n\n{messages.MENU_AYUDA}"
            buttons = get_menu_ayuda_buttons(new_previous_state)
            image_id = None

        # Si veníamos de DUDA/MENU_DUDA u otro estado fuera de flujo, preservar el previous_state de la sesión
        if original_state_for_previous in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]:
            saved_previous = session.previous_state
        else:
            saved_previous = original_state_for_previous.value

        return FlowResult(
            reply=reply,
            next_state=current_state,
            buttons=buttons,
            previous_state=saved_previous,
            image_id=image_id
        )
    
    # --------------------------------------
    # DETECCIÓN DE FRUSTRACIÓN
    # --------------------------------------
    if detect_frustration(text):
        session.ai_response_attempts = (getattr(session, "ai_response_attempts", 0) or 0) + 1

    # --------------------------------------
    # IA: INTENCIÓN NO DETECTADA (ai_out, ai_ambiguous)
    # --------------------------------------
    if action in ("ai_out", "ai_ambiguous") and not (intent and intent.isupper()):
        # Si ya terminó (checkpoint terminal), usar un texto más directo
        if new_previous_state and is_terminal_state(ChatState(new_previous_state)):
            msg_reply = f"{messages.NO_ENTENDIDO}\n\n{messages.EN_QUE_MAS_AYUDAR}"
        else:
            msg_reply = f"{messages.NO_ENTENDIDO}\n\n{messages.MENU_AYUDA}"

        #logger.info(f"❓ [Flujo] Fallback de estado. Redirigiendo a MENU_AYUDA (no se entendió en {current_state.value}).")
        return FlowResult(
            reply=msg_reply,
            next_state=ChatState.MENU_AYUDA,
            buttons=get_menu_ayuda_buttons(new_previous_state),
            previous_state=new_previous_state
        )

    # --------------------------------------
    # IA: DUDAS (ai_doubt)
    # --------------------------------------
    if action == "ai_doubt" and not (intent and intent.isupper()):

        MAX_AI_RESPONSES = 2
        ai_attempts = getattr(session, "ai_response_attempts", 0) or 0

        # "Si no pudo ayudarlo (supera intentos de frustración), escalar el caso"
        if ai_attempts >= MAX_AI_RESPONSES:
            _log()
        
            return FlowResult(
                reply=messages.ACLARACION,
                next_state=ChatState.ACLARACION,
                buttons=FLOW.get(ChatState.ACLARACION, {}).get("buttons", []),
                previous_state=new_previous_state
            )

        # Generar respuesta IA para responder la duda
        ai_reply = generate_ai_response(text, context, session=session)

        if not ai_reply or not ai_reply.strip():
            ai_reply = messages.ERROR_IA

        # Detectar si la IA decidió escalar
        from app.services.ai.agent_messages import AGENT_MESSAGES
        if ai_reply.strip() in [
            AGENT_MESSAGES["escalation"]["default"],
            AGENT_MESSAGES["fallback"]["default"]
        ] or "asesor" in ai_reply.lower():
            return FlowResult(
                reply=ai_reply,
                next_state=ChatState.LLAMADA,
                buttons=[],
                previous_state=new_previous_state
            )

        current_state = ChatState(session.state)
        # Capturamos el estado original ANTES de cualquier reasignación
        original_state_for_previous = current_state

        reply_state, buttons, image_id = render_state(
            current_state,
            session,
            db
        )

        # Estados donde NO queremos concatenar la pregunta de verificación:
        # - estados no-verificación (menú, duda, fuera de flujo...)
        # - estados de INFORMACIÓN: el mensaje ya es largo, mostramos solo el menú
        is_info_state = get_state_type(current_state) == "information"
        skip_verification_append = (
            current_state in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA,
                              ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]
            or is_info_state
        )

        is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

        if is_finished:
            current_state = ChatState.FINALIZADO
            reply = f"{ai_reply}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            image_id = None
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif not skip_verification_append and reply_state:
            reply = f"{ai_reply}\n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
        else:
            #logger.info(f"⏭️ [Flujo] Redirigiendo a MENU_AYUDA (Duda IA en estado {original_state_for_previous.value}).")
            current_state = ChatState.MENU_AYUDA
            reply = f"{ai_reply}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            buttons = get_menu_ayuda_buttons(new_previous_state)
            image_id = None

        # Si veníamos de DUDA/MENU_DUDA u otro estado fuera de flujo, preservar el previous_state de la sesión.
        # Si veníamos de un estado de información directamente, también lo guardamos
        # como previous_state para que "Ir a verificación" regrese al lugar correcto.
        if original_state_for_previous in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO]:
            saved_previous = session.previous_state
        else:
            saved_previous = session.state  # INFO_PAGOS, CONFIRMAR_xxx, etc.

        return FlowResult(
            reply=reply,
            next_state=current_state,
            buttons=buttons,
            previous_state=saved_previous,
            image_id=image_id
        )
        
    # --------------------------------------
    # 9. Resolver siguiente estado
    # --------------------------------------

    next_state = resolve_next_state(
        current_state=current_state,
        action=action,
        detected_intent=detected_intent,
        previous_state=previous_state
    )

    skip_tracking = False
    is_jump_ahead_active = session.extra_json and "verification_suspended_state" in session.extra_json
    returned_from_jump = False

    # Limpieza de seguridad: Si el usuario ya regresó a una pregunta de confirmación, 
    # pero el estado suspendido seguía en BD por caché de SQLAlchemy, lo limpiamos para evitar loops.
    if is_jump_ahead_active and get_state_type(current_state) == "confirmation":
        new_extra = dict(session.extra_json)
        new_extra.pop("verification_suspended_state", None)
        session.extra_json = new_extra
        is_jump_ahead_active = False

    # Interceptar si venimos de un estado saltado (jump-ahead) y el usuario confirmó/avanzó
    if is_jump_ahead_active and get_state_type(current_state) == "information":
        if next_state in (ChatState.DUDA, ChatState.MENU_DUDA):
            # El usuario tiene una duda sobre la información saltada, le permitimos ir a preguntar.
            pass
        elif action == "advance" or detected_intent == "affirmative":
            skip_tracking = True
            # 1. Marcar el paso de información actual como completado en VerificacionCuenta
            from app.services.verification_tracker import STEP_MAP
            jumped_step = STEP_MAP.get(current_state)
            if jumped_step and db and session.folio:
                try:
                    service = VerificationService(db)
                    no_cuenta = service.resolve_no_cuenta_from_folio(session.folio) or _no_cuenta_from_bridge(session, session.folio, bridge_verification)
                    if no_cuenta:
                        service.update_step_atomic(
                            no_cuenta=no_cuenta,
                            step=jumped_step,
                            value=1,
                            phone=session.phone,
                            allow_out_of_order=True,
                            allow_override=True
                        )
                except Exception as e:
                    logger.warning(f"Error marking jumped step {jumped_step} on confirm: {e}")
            
            # 2. Retomar el estado original suspendido
            new_extra = dict(session.extra_json)
            suspended_state_val = new_extra.pop("verification_suspended_state", ChatState.INICIO.value)
            session.extra_json = new_extra
            next_state = ChatState(suspended_state_val)
            returned_from_jump = True

        elif detected_intent == "negative":
            skip_tracking = True
            # El usuario explícitamente no entendió o no confirmó la información saltada.
            # Retornamos al estado original SIN marcar el paso, para que se le muestre de nuevo más adelante.
            new_extra = dict(session.extra_json)
            suspended_state_val = new_extra.pop("verification_suspended_state", ChatState.INICIO.value)
            session.extra_json = new_extra
            next_state = ChatState(suspended_state_val)

    # Si el flujo va a un estado de cambio de folio, limpiar el folio de la sesión
    if next_state in (ChatState.CAMBIAR_FOLIO, ChatState.CAMBIAR_FOLIO_DEVOLUCION, ChatState.CAMBIAR_FOLIO_DESCUENTO):
        session.folio = None

    # --------------------------------------
    # FIX RESUME (__RESUME__)
    # --------------------------------------
    if next_state == "__RESUME__":
        next_state = ChatState(previous_state) if previous_state else ChatState.INICIO

    if next_state == "__RESUME_DESCUENTO__":
        venta = _venta_or_bridge_for_folio(db, session, session.folio, bridge_verification)
        if venta:
            desglose = MessageBuilder.build_descuento_desglose(venta)
            return FlowResult(
                reply=f"{desglose}\n\n{messages.EN_QUE_MAS_AYUDAR}",
                next_state=ChatState.MENU_AYUDA,
                buttons=get_menu_ayuda_buttons(new_previous_state),
                previous_state=new_previous_state
            )
        else:
            next_state = ChatState.INICIO

    if not next_state:
        next_state = ChatState.MENU_AYUDA

    if action == "repeat" and next_state == current_state:
        reply, buttons, image_id = render_state(
            current_state,
            session,
            db
        )
        return FlowResult(
            reply=reply,
            next_state=current_state,
            buttons=buttons,
            previous_state=new_previous_state,
            image_id=image_id
        )

    # --------------------------------------
    # 10. Tracking
    # --------------------------------------

    if not skip_tracking:
        track_verification(
            db=db,
            session=session,
            current_state=current_state,
            detected_intent=detected_intent,
            bridge_verification=bridge_verification,
            allow_out_of_order=is_jump_ahead_active,
        )

    # --------------------------------------
    # 11. Saltos
    # --------------------------------------

    next_state = handle_flow_skips(context, next_state)

    # --------------------------------------
    # 12. Render
    # --------------------------------------

    reply, buttons, image_id = render_state(
        next_state,
        session,
        db
    )
    
    if returned_from_jump:
        prefix = "🔁 ¡Excelente! Volvamos a donde nos quedamos en tu verificación para terminar tu registro."
        reply = f"{prefix}\n\n{reply}" if reply else prefix
        
    _log()
        

    return FlowResult(
        reply=reply,
        next_state=next_state,
        buttons=buttons,
        previous_state=new_previous_state,
        image_id=image_id
    )
