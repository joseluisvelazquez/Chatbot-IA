from __future__ import annotations

from dataclasses import dataclass
import logging

from app.core.states.states import ChatState
from app.core.intents.intents import detect_intent
from app.core.intents.intent_router import route_intent
from app.core.states.state_resolver import resolve_next_state
from app.core.states.state_renderer import render_state
from app.core.states.state_handlers import handle_special_cases, handle_flow_skips
from app.core.context.conversation_context import ConversationContext
from app.core.states.state_types import get_state_type
from app.core.flow.flow import FLOW
from app.config.settings import settings

from app.content import messages
from app.content.message_builder import MessageBuilder
from app.services import verification_service
from app.siga.siga_repository import obtener_venta_por_folio, obtener_verificacion_por_no_cuenta
from app.utils.folio_parser import extraer_folio

from app.services.verification_service import VerificationService, log_flow_event
from app.services.verification_tracker import track_verification
from app.services.ai.ai_service import analyze_inconsistency, generate_ai_response
from app.services.inconsistencias_service import open_or_patch_inconsistencia
from app.services.ai.intent_interpreter import interpret_intent_with_ai, should_use_ai, is_doubt, detect_frustration
from app.services.faq.faq_service import find_faq_answer

logger = logging.getLogger(__name__)


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

def _try_mark_step(db, session, step_key: str):
    if not db:
        return

    folio = getattr(session, "folio", None)
    if not folio:
        return

    try:
        VerificationService(db).mark_step_from_folio(
            str(folio),
            step_key,
            1,
            phone=session.phone,
        )
    except Exception:
        logger.exception("Error guardando progreso")

def is_descuento_query(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    keywords = [
        "descuento",
        "subsidio",
        "se descuenta",
        "me dijeron descuento",
        "pago inicial descuento",
        "me iban a descontar",
        "calificacion estudiante",
    ]

    return any(k in text for k in keywords)

def is_devolucion_query(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    keywords = [
        "devolver",
        "devolucion",
        "quiero devolver",
        "cancelar compra",
        "regresar equipo",
        "ya no lo quiero",
    ]

    return any(k in text for k in keywords)


# --------------------------------------
# MAIN
# --------------------------------------

def process_message(session, text: str, intent: str | None = None, db=None) -> FlowResult:

    # --------------------------------------
    # Si mandó folio para iniciar
    # --------------------------------------
    def _check_verification_complete(folio: str) -> FlowResult | None:    
        no_cuenta = VerificationService(db).resolve_no_cuenta_from_folio(folio)
        verificacion = obtener_verificacion_por_no_cuenta(db,no_cuenta)
        print(f"DEBUG: Folio detectado {folio} con no_cuenta {no_cuenta}")

        if no_cuenta and verificacion and (session.phone not in settings.TEST_PHONE_ONLY):

            print(verification_service.is_verification_complete(verificacion.json))

            if verification_service.is_verification_complete(verificacion.json):
                return FlowResult(
                    reply="✅ Esta cuenta ya fue verificada anteriormente.",
                    next_state=ChatState.MENU_AYUDA,
                    buttons= FLOW[ChatState.MENU_AYUDA].get("buttons", []),
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

    current_state = ChatState(session.state)
    previous_state = session.previous_state

    # --------------------------------------
    # 1. Detectar intención (con fallback IA)
    # --------------------------------------

    folio = None

    if intent and intent.isupper():
        detected_intent = intent
        action = "advance"
    else:
        # --------------------------------------
        # 1. Detectar intención (con prioridad)
        # --------------------------------------
        text_clean = text.strip().lower()

        import re
        import unicodedata

        def clean_for_match(txt):
            normalized = unicodedata.normalize('NFKD', txt).encode('ASCII', 'ignore').decode('utf-8')
            return re.sub(r'[^a-z0-9\s]', '', normalized).strip()

        text_norm = clean_for_match(text_clean)
        
        button_matched = False
        state_buttons = FLOW.get(current_state, {}).get("buttons", [])
        
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
            elif current_state == ChatState.MENU_AYUDA and "verificacion" in text_clean:
                detected_intent = "MENU_VERIFICACION"
                action = "advance"
                folio = None
            else:
                detected_intent, folio = detect_intent(text, current_state)

                # detectar duda explícita si detect_intent no fue crítico
                if is_doubt(text) and detected_intent not in ("human", "call", "start_verification"):
                    detected_intent = "doubt"

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
                detected_intent = "doubt"      # no entendió
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
            session=session,
            db=db
        )

        state_type = get_state_type(current_state)

        # decidir uso de IA según estado
        if state_type == "confirmation":
            use_ai = False  # casi nunca usar IA aquí

        elif state_type == "information":
            use_ai = True   # aquí sí es útil

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
        elif detected_intent in PROTECTED_INTENTS and use_ai:

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

    # --------------------------------------
    # 2. Detectar folio automático
    # --------------------------------------

    folio_detectado = extraer_folio(text)

    if folio_detectado and not session.folio:
        venta = obtener_venta_por_folio(db, folio_detectado)

        if venta:
            session.folio = folio_detectado

            target_state = ChatState.CONFIRMAR_FOLIO
            if current_state == ChatState.CAMBIAR_FOLIO_DEVOLUCION:
                target_state = ChatState.CONFIRMAR_FOLIO_DEVOLUCION
            elif current_state == ChatState.CAMBIAR_FOLIO_DESCUENTO:
                target_state = ChatState.CONFIRMAR_FOLIO_DESCUENTO
            
            verification_result = _check_verification_complete(folio_detectado)

            if verification_result:
                return verification_result

            _log(target_state)

            return FlowResult(
                reply=messages.CONFIRMAR_FOLIO_DETECTADO.format(folio=folio_detectado),
                next_state=target_state,
                buttons=FLOW.get(target_state, {}).get("buttons", [])
            )

    # --------------------------------------
    # 3. Menú fuera de flujo
    # --------------------------------------

    if current_state in [ChatState.ESPERA, ChatState.FUERA_DE_FLUJO] and action != "advance" and detected_intent != "start_verification":
        return FlowResult(
            reply=messages.MENU_AYUDA,
            next_state=ChatState.MENU_AYUDA,
            buttons=FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
        )

    # --------------------------------------
    # 4. Inicio verificación
    # --------------------------------------

    if detected_intent == "start_verification":
        venta = obtener_venta_por_folio(db, folio)

        if not venta:
            return FlowResult(
                "❌ No encontramos tu folio. Verifica e intenta nuevamente.",
                current_state,
                FLOW.get(current_state, {}).get("buttons", [])
            )
        
        verification_result = _check_verification_complete(folio)

        if verification_result:
            return verification_result

        session.folio = folio

        

        _log(ChatState.CONFIRMAR_FOLIO)

        return FlowResult(
            reply=messages.CONFIRMAR_FOLIO_DETECTADO.format(folio=folio),
            next_state=ChatState.CONFIRMAR_FOLIO,
            buttons=FLOW.get(ChatState.CONFIRMAR_FOLIO, {}).get("buttons", [])
        )

    # --------------------------------------
    # 5. Contexto
    # --------------------------------------

    venta = obtener_venta_por_folio(db, session.folio) if session.folio else None

    context = ConversationContext(
        state=current_state,
        previous_state=previous_state,
        text=text,
        intent=detected_intent,
        phone=session.phone,
        folio=session.folio,
        venta=venta,
        session=session,
        db=db
    )

    # --------------------------------------
    # PROCESAR INCONSISTENCIA (IA)
    # --------------------------------------

    is_direct_inconsistency = (
        get_state_type(current_state) == "confirmation" and
        detected_intent == "negative" and
        len(text.split()) > 2
    )

    if current_state == ChatState.INCONSISTENCIA or is_direct_inconsistency:

        result = analyze_inconsistency(text, context, session=session)
        print(" RESULTADO IA:", result)

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

        print("SEVERIDAD:", severidad, "| CONTADOR:", contador, "| MODERADAS EFECTIVAS:", moderadas_efectivas)

        # 🔴 crítica → parar flujo y cerrar registro
        if severidad == "critica":
            from app.services.inconsistencias_service import close_open_inconsistencia
            close_open_inconsistencia(db=db, phone=session.phone, folio=session.folio, session_id=session.id)
            return FlowResult(
                reply=messages.ESCALAMIENTO_CRITICO,
                next_state=ChatState.ACLARACION,
                buttons=[],
                previous_state=session.state
            )

        # 🟡 demasiadas inconsistencias → parar flujo y cerrar registro
        if moderadas_efectivas > 2 or contador["total"] > 3:
            from app.services.inconsistencias_service import close_open_inconsistencia
            close_open_inconsistencia(db=db, phone=session.phone, folio=session.folio, session_id=session.id)
            return FlowResult(
                reply=messages.ESCALAMIENTO_MULTIPLES,
                next_state=ChatState.ACLARACION,
                buttons=[],
                previous_state=session.state
            )

        # 🟢 continuar flujo
        LEVE_NEXT_STATE = {
            ChatState.CONFIRMAR_NOMBRE:          ChatState.CONFIRMAR_DOMICILIO,
            ChatState.CONFIRMAR_DOMICILIO:       ChatState.CONFIRMAR_FECHA,
            ChatState.CONFIRMAR_FECHA:           ChatState.CONFIRMAR_PRODUCTO,
            ChatState.CONFIRMAR_PRODUCTO:        ChatState.CONFIRMAR_COMPONENTES,
            ChatState.CONFIRMAR_ESTADO_PRODUCTO: ChatState.CONFIRMAR_PAGO_INICIAL,
            ChatState.CONFIRMAR_PAGO_INICIAL:    ChatState.INFO_PAGOS,
        }

        origen_inco = previous_state if current_state == ChatState.INCONSISTENCIA else current_state
        prev = ChatState(origen_inco) if origen_inco else None
        next_state = LEVE_NEXT_STATE.get(prev) or prev or ChatState.INICIO

        next_state = handle_flow_skips(context, next_state)

        reply_state, buttons, image_id = render_state(next_state, session, db)
        reply = f"{messages.CORRECCION_REGISTRADA}\n\n{reply_state}" if reply_state else messages.CORRECCION_REGISTRADA

        _log()

        return FlowResult(
            reply=reply,
            next_state=next_state,
            buttons=buttons,
            previous_state=session.state,
            image_id=image_id,
        )


    # --------------------------------------
    # 6. HANDLERS ESPECIALES
    # --------------------------------------

    special = handle_special_cases(context)

    if special:
        special_state = special.get("state")
        _log(special_state)

        return FlowResult(
            reply=special.get("reply"),
            next_state=special_state,
            buttons=special.get("buttons", []),
            previous_state=session.state,
            inconsistencia_patch=special.get("patch"),
            image_id=special.get("image_id"),
        )

    # --------------------------------------
    # 7. ACCIONES DIRECTAS (ESCALAMIENTO)
    # --------------------------------------

    if action == "escalate":
        _log(ChatState.ACLARACION)
        return FlowResult(
            reply=messages.ACLARACION,
            next_state=ChatState.ACLARACION,
            buttons=FLOW[ChatState.ACLARACION].get("buttons", []),
            previous_state=session.state
        )

    if action == "escalate_call":
        _log(ChatState.LLAMADA)
        return FlowResult(
            reply=messages.ACLARACION,
            next_state=ChatState.LLAMADA,
            buttons=FLOW[ChatState.LLAMADA].get("buttons", []),
            previous_state=session.state
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
                previous_state=session.state
            )

        venta = obtener_venta_por_folio(db, session.folio)

        if venta:
            desglose = MessageBuilder.build_descuento_desglose(venta)

            current_state = ChatState(session.state)
            original_state_for_previous = current_state

            is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

            if is_finished:
                current_state = ChatState.FINALIZADO
                reply = desglose
                image_id = None
                buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
            else:
                current_state = ChatState.MENU_AYUDA
                reply = f"{desglose}\n\n{messages.EN_QUE_MAS_AYUDAR}"
                buttons = FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
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
                previous_state=session.state
            )
        


        return FlowResult(
            reply=MessageBuilder.build_devolucion_confirmacion(),
            next_state=ChatState.DEVOLUCION_CONFIRMAR,
            buttons=FLOW.get(ChatState.DEVOLUCION_CONFIRMAR, {}).get("buttons", []),
            previous_state=session.state
        )
    
    # --------------------------------------
    # 8. IA (CONTROLADA POR TIPO)
    # --------------------------------------

    # --------------------------------------
    # FAQ (RESPUESTA DIRECTA SIN IA)
    # --------------------------------------

    faq_response, faq_image_id = find_faq_answer(text, context.venta)

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
            reply = faq_response
            image_id = faq_image_id
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif not skip_verification_append and reply_state:
            reply = f"{faq_response}\n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
            image_id = faq_image_id or image_id
        else:
            current_state = ChatState.MENU_AYUDA
            reply = f"{faq_response}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            buttons = FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
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
        
        current_state = ChatState(session.state)
        # Capturamos el estado original ANTES de cualquier reasignación
        original_state_for_previous = current_state
        reply_state, buttons, image_id = render_state(current_state, session, db)

        is_finished = (current_state == ChatState.FINALIZADO) or (session.previous_state == "FINALIZADO")

        if is_finished:
            current_state = ChatState.FINALIZADO
            reply = "👋🏻 ¡Hola!"
            image_id = None
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif current_state not in [ChatState.MENU_AYUDA, ChatState.MENU_DUDA, ChatState.DUDA, ChatState.ESPERA, ChatState.FUERA_DE_FLUJO] and reply_state:
            reply = f"👋🏻 ¡Hola! \n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
        else:
            current_state = ChatState.MENU_AYUDA
            reply = f"👋🏻 ¡Hola! \n\n{messages.MENU_AYUDA}"
            buttons = FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
            image_id = None

        # Si veníamos de DUDA/MENU_DUDA u otro estado fuera de flujo, preservar el previous_state de la sesión
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
    # DETECCIÓN DE FRUSTRACIÓN
    # --------------------------------------
    if detect_frustration(text):
        session.ai_response_attempts = (session.ai_response_attempts or 0) + 1

    # --------------------------------------
    # IA: INTENCIÓN NO DETECTADA (ai_out, ai_ambiguous)
    # --------------------------------------
    if action in ("ai_out", "ai_ambiguous") and not (intent and intent.isupper()):
        # "Si de plano no entiende, mostrar el menú de ayuda"
        return FlowResult(
            reply=f"{messages.NO_ENTENDIDO}\n\n{messages.MENU_AYUDA}",
            next_state=ChatState.MENU_AYUDA,
            buttons=FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", []),
            previous_state=session.state
        )

    # --------------------------------------
    # IA: DUDAS (ai_doubt)
    # --------------------------------------
    if action == "ai_doubt" and not (intent and intent.isupper()):

        MAX_AI_RESPONSES = 2
        ai_attempts = session.ai_response_attempts or 0

        # "Si no pudo ayudarlo (supera intentos de frustración), escalar el caso"
        if ai_attempts >= MAX_AI_RESPONSES:
            _log()
        
            return FlowResult(
                reply=messages.ACLARACION,
                next_state=ChatState.ACLARACION,
                buttons=FLOW.get(ChatState.ACLARACION, {}).get("buttons", []),
                previous_state=session.state
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
                next_state=ChatState.ACLARACION,
                buttons=[],
                previous_state=session.state
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
            reply = ai_reply
            image_id = None
            buttons = FLOW.get(ChatState.FINALIZADO, {}).get("buttons", [])
        elif not skip_verification_append and reply_state:
            reply = f"{ai_reply}\n\n{messages.CONTINUAR_VERIFICACION}\n\n{reply_state}"
        else:
            current_state = ChatState.MENU_AYUDA
            reply = f"{ai_reply}\n\n{messages.EN_QUE_MAS_AYUDAR}"
            buttons = FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
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

    # --------------------------------------
    # FIX RESUME (__RESUME__)
    # --------------------------------------
    if next_state == "__RESUME__":
        next_state = ChatState(previous_state) if previous_state else ChatState.INICIO

    if next_state == "__RESUME_DESCUENTO__":
        venta = obtener_venta_por_folio(db, session.folio)
        if venta:
            desglose = MessageBuilder.build_descuento_desglose(venta)
            return FlowResult(
                reply=f"{desglose}\n\n{messages.EN_QUE_MAS_AYUDAR}",
                next_state=ChatState.MENU_AYUDA,
                buttons=FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", []),
                previous_state=session.state
            )
        else:
            next_state = ChatState.INICIO

    if not next_state:
        next_state = ChatState.FUERA_DE_FLUJO

    # --------------------------------------
    # 10. Tracking
    # --------------------------------------

    track_verification(
        db=db,
        session=session,
        current_state=current_state,
        detected_intent=detected_intent,
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
    _log()
        

    return FlowResult(
        reply=reply,
        next_state=next_state,
        buttons=buttons,
        previous_state=session.state,
        image_id=image_id
    )
