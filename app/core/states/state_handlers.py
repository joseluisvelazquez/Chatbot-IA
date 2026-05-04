from app.core.states.states import ChatState
from app.core.flow.flow import FLOW

from app.content import messages as msg
from app.siga.siga_repository import obtener_venta_por_folio
from app.utils.folio_parser import extraer_folio
from app.services.inconsistencias_service import (
    get_open_inconsistencia,
    open_or_patch_inconsistencia,
    close_open_inconsistencia,
)
from app.config.settings import settings

# -----------------------------
# MAPS
# -----------------------------

COMPONENTES_MAP = {
    "FALT_CPU": {"db": "CPU roja", "label": "🔴 CPU roja", "image_env": "IMAGE_ID_CPU", "aliases": ["cpu de color rojo", "cpu rojo", "color rojo", "cpu"]},
    "FALT_MONITOR": {"db": "Monitor", "label": "🖥️ Monitor", "image_env": "IMAGE_ID_MONITOR", "aliases": ["monitor o pantalla", "pantalla"]},
    "FALT_TECLADO": {"db": "Teclado", "label": "⌨️ Teclado", "image_env": "IMAGE_ID_TECLADO", "aliases": []},
    "FALT_MOUSE": {"db": "Mouse", "label": "🖱️ Mouse", "image_env": "IMAGE_ID_MOUSE", "aliases": ["raton", "ratón", "mause"]},
    "FALT_BOCINAS": {"db": "Bocinas", "label": "🔊 Bocinas", "image_env": "IMAGE_ID_BOCINAS", "aliases": ["par de bocinas", "par", "bocina"]},
    "FALT_REGULADOR": {"db": "Regulador", "label": "🔌 Regulador", "image_env": "IMAGE_ID_REGULADOR", "aliases": ["regulador de voltaje", "voltaje"]},
    "FALT_WIFI": {"db": "Antena WiFi", "label": "📶 Antena WiFi", "image_env": "IMAGE_ID_WIFI", "aliases": ["antena", "adaptador wifi", "antena wifi usb"]},
}

INCONSISTENCIAS_MAP = {
    ChatState.CONFIRMAR_NOMBRE: "nombre",
    ChatState.CONFIRMAR_DOMICILIO: "domicilio",
    ChatState.CONFIRMAR_FECHA: "fecha_venta",
    ChatState.CONFIRMAR_PRODUCTO: "producto",
    ChatState.CONFIRMAR_PAGO_INICIAL: "pago_inicial",
}


# -----------------------------
# 1. CAMBIO DE FOLIO
# -----------------------------

def handle_cambiar_folio(context):
    if context.state not in [ChatState.CAMBIAR_FOLIO, ChatState.CAMBIAR_FOLIO_DEVOLUCION, ChatState.CAMBIAR_FOLIO_DESCUENTO]:
        return None

    nuevo_folio = extraer_folio(context.text)
    
    venta = obtener_venta_por_folio(context.db, nuevo_folio) if nuevo_folio else None

    if not nuevo_folio or not venta:
        # Flujo Reactivo: El folio es válido pero aún no existe en DB (Solo para verificación normal)
        if context.state == ChatState.CAMBIAR_FOLIO and nuevo_folio and not venta:
            context.session.invalid_folio_attempts = 0
            context.session.folio = nuevo_folio
            return {
                "reply": msg.SALA_ESPERA.format(folio=nuevo_folio),
                "state": ChatState.ESPERANDO_REGISTRO,
                "buttons": [{"id": "CAMBIAR_FOLIO", "label": "✏️ Cambiar folio"}]
            }
            
        # Flujo de Error: No tiene formato de folio válido, o es devolución/descuento y no existe
        attempts = getattr(context.session, "invalid_folio_attempts", 0) + 1
        context.session.invalid_folio_attempts = attempts
        
        if attempts >= 3:
            context.session.invalid_folio_attempts = 0
            return {
                "reply": "🔍 ¡Ups! No logré localizar ese número de folio en mi sistema.\n\n" + msg.MENU_AYUDA,
                "state": ChatState.MENU_AYUDA,
                "buttons": FLOW.get(ChatState.MENU_AYUDA, {}).get("buttons", [])
            }
            
        reply = msg.FOLIO_NO_DETECTADO if not nuevo_folio else msg.FOLIO_NO_EXISTE
        return {
            "reply": reply,
            "state": context.state
        }

    context.session.invalid_folio_attempts = 0
    context.session.folio = nuevo_folio

    target_state = ChatState.INICIO2
    if context.state == ChatState.CAMBIAR_FOLIO_DEVOLUCION:
        target_state = ChatState.CONFIRMAR_FOLIO_DEVOLUCION
    elif context.state == ChatState.CAMBIAR_FOLIO_DESCUENTO:
        target_state = ChatState.CONFIRMAR_FOLIO_DESCUENTO

    if target_state == ChatState.INICIO2:
        from app.core.states.state_renderer import render_state
        reply_state, buttons, _ = render_state(target_state, context.session, context.db)
        return {
            "reply": reply_state,
            "state": target_state,
            "buttons": buttons
        }

    return {
        "reply": msg.CONFIRMAR_FOLIO_DETECTADO.format(folio=nuevo_folio),
        "state": target_state,
        "buttons": FLOW[target_state].get("buttons", [])
    }


def handle_menu(context):

    from app.core.states.state_renderer import render_state

    # -------------------------
    # OPCIÓN: HACER PREGUNTA
    # -------------------------
    if context.intent == "MENU_DUDA":
        return {
            "reply": msg.PREGUNTA_DUDA,
            "state": ChatState.MENU_DUDA,
            "buttons": []
        }

    # -------------------------
    # OPCIÓN: IR A VERIFICACIÓN
    # -------------------------
    if context.intent == "MENU_VERIFICACION":

        # si la sesión actual ya terminó (FINALIZADO), limpiamos el folio
        if context.session.folio and context.state == ChatState.FINALIZADO:
            context.session.folio = None

        if not context.session.folio:
            from app.siga.siga_repository import obtener_folios_pendientes_por_telefono
            
            pendientes = obtener_folios_pendientes_por_telefono(context.db, context.session.phone)
            
            if len(pendientes) == 0:
                return {
                    "reply": msg.PEDIR_FOLIO,
                    "state": ChatState.CAMBIAR_FOLIO,
                    "buttons": FLOW.get(ChatState.CAMBIAR_FOLIO, {}).get("buttons", [])
                }
            elif len(pendientes) == 1:
                context.session.folio = pendientes[0]
                target_state = ChatState.INICIO2
                from app.core.states.state_renderer import render_state
                reply_state, buttons, _ = render_state(target_state, context.session, context.db)
                return {
                    "reply": reply_state,
                    "state": target_state,
                    "buttons": buttons
                }
            elif len(pendientes) > 1:
                # Mostrar botones para seleccionar folio (si son > 3, whatsapp client lo convierte en lista)
                botones = [{"id": f"SELECCIONAR_FOLIO_{f}", "label": f"Folio {f}"} for f in pendientes[:10]]
                return {
                    "reply": msg.MULTIPLES_FOLIOS_PENDIENTES.format(cantidad=len(pendientes)),
                    "state": ChatState.SELECCIONAR_FOLIO,
                    "buttons": botones
                }

        # si ya tiene estado → continuar (al anterior)
        try:
            resume_state = ChatState(context.previous_state) if context.previous_state else ChatState.INICIO
            ignore_states = {
                ChatState.INICIO,
                ChatState.MENU_AYUDA, 
                ChatState.MENU_DUDA, 
                ChatState.DUDA,          # no reanudar dentro de un estado de duda
                ChatState.ESPERA, 
                ChatState.FUERA_DE_FLUJO,
                ChatState.CAMBIAR_FOLIO,
                ChatState.CAMBIAR_FOLIO_DEVOLUCION,
                ChatState.CAMBIAR_FOLIO_DESCUENTO,
                ChatState.CONFIRMAR_FOLIO_DEVOLUCION,
                ChatState.CONFIRMAR_FOLIO_DESCUENTO,
                ChatState.ACLARACION,
                ChatState.FINALIZADO,
                ChatState.LLAMADA,
            }
            if resume_state in ignore_states:
                resume_state = ChatState.INICIO
        except ValueError:
            resume_state = ChatState.INICIO

        rendered_reply, rendered_buttons, rendered_img = render_state(resume_state, context.session, context.db)

        reply_text = msg.CONTINUAR_VERIFICACION_MENU
        if rendered_reply:
            reply_text += f"\n\n{rendered_reply}"

        return {
            "reply": reply_text,
            "state": resume_state,
            "buttons": rendered_buttons if rendered_buttons else FLOW.get(resume_state, {}).get("buttons", []),
            "image_id": rendered_img
        }

    return None

# -----------------------------
# 2. INCONSISTENCIA 
# -----------------------------

def handle_inconsistencia(context):
   return None

# -----------------------------
# 2.5 SELECCIONAR FOLIO MULTIPLE
# -----------------------------
def handle_seleccionar_folio(context):
    if context.state == ChatState.SELECCIONAR_FOLIO:
        folio = None
        
        # 1. Si el usuario seleccionó una opción de la lista o botón
        if context.intent and context.intent.startswith("SELECCIONAR_FOLIO_"):
            folio = context.intent.replace("SELECCIONAR_FOLIO_", "")
            
        # 2. Si el usuario escribió el folio manualmente
        elif context.text:
            from app.utils.folio_parser import extraer_folio
            folio = extraer_folio(context.text)

        if folio:
            # Validar que el folio pertenezca a sus pendientes
            from app.siga.siga_repository import obtener_folios_pendientes_por_telefono
            pendientes = obtener_folios_pendientes_por_telefono(context.db, context.session.phone)
            
            # Convertimos ambos a string por seguridad
            if str(folio) in [str(f) for f in pendientes]:
                context.session.folio = folio
                
                target_state = ChatState.INICIO2
                from app.core.states.state_renderer import render_state
                reply_state, buttons, _ = render_state(target_state, context.session, context.db)
                return {
                    "reply": reply_state,
                    "state": target_state,
                    "buttons": buttons
                }
            else:
                # Si escribió un folio que no está en sus pendientes
                botones = [{"id": f"SELECCIONAR_FOLIO_{f}", "label": f"Folio {f}"} for f in pendientes[:10]]
                return {
                    "reply": f"⚠️ El folio *{folio}* no se encuentra en tu lista de compras pendientes.\n\nPor favor selecciona o escribe uno de los folios mostrados:",
                    "state": ChatState.SELECCIONAR_FOLIO,
                    "buttons": botones
                }
    return None


# -----------------------------
# HELPER: componentes ya reportados
# -----------------------------

def _get_componentes_ya_reportados(extra_json: dict) -> list:
    """
    Extrae los nombres (db) de componentes ya confirmados como faltantes
    desde la lista de inconsistencias.
    """
    for entry in extra_json.get("inconsistencias", []):
        if entry.get("estado_origen") != "CONFIRMAR_COMPONENTES":
            continue
        # Entrada consolidada (2+ componentes)
        if "elementos_faltantes" in entry:
            return list(entry["elementos_faltantes"])
        # Entrada simple (1 componente): parsear del mensaje
        mensaje = entry.get("mensaje_cliente", "")
        for comp in COMPONENTES_MAP.values():
            if comp["db"] in mensaje:
                return [comp["db"]]
    return []


# -----------------------------
# 3. COMPONENTE SELECCIONADO
# -----------------------------

def handle_componentes(context):
    if context.state != ChatState.COMPONENTES_FALTANTES:
        return None

    if context.intent not in COMPONENTES_MAP:
        return None

    componente = COMPONENTES_MAP[context.intent]

    # Guardamos en sesión Y en patch para persistencia qué componente estamos revisando
    context.session.componente_en_verificacion = context.intent

    # Obtener image_id desde settings usando la clave image_env del componente
    env_var = componente.get("image_env")
    image_id = getattr(settings, env_var, None) if env_var else None

    return {
        "reply": msg.VERIFICAR_FOTO_COMPONENTE.format(componente=componente['label']),
        "state": ChatState.VERIFICAR_FOTO_COMPONENTE,
        "buttons": FLOW[ChatState.VERIFICAR_FOTO_COMPONENTE].get("buttons", []),
        "patch": {
            "componentes_temp": {
                "componente_en_verificacion": context.intent
            }
        },
        "image_id": image_id,
    }


def handle_verificar_foto(context):
    if context.state != ChatState.VERIFICAR_FOTO_COMPONENTE:
        return None

    # Intentar obtener de sesión (memoria) o de Inconsistencias (DB)
    intent_comp = getattr(context.session, "componente_en_verificacion", None)

    if not intent_comp:
        inc = get_open_inconsistencia(context.db, context.phone, context.folio, context.session.id)
        if inc and inc.extra_json:
            intent_comp = inc.extra_json.get("componentes_temp", {}).get("componente_en_verificacion")

    if not intent_comp or intent_comp not in COMPONENTES_MAP:
        return None

    componente = COMPONENTES_MAP[intent_comp]

    if context.intent in ["FOTO_SI_FALTA", "affirmative"]:

        # --------------------------------------
        # Leer estado actual de la BD
        # --------------------------------------
        inc = get_open_inconsistencia(context.db, context.phone, context.folio, context.session.id)
        extra = inc.extra_json if inc and inc.extra_json else {}

        # Componentes ya confirmados + el nuevo
        ya_reportados = _get_componentes_ya_reportados(extra)
        todos_faltantes = ya_reportados + [componente["db"]]
        total = len(todos_faltantes)

        # Severidad: 1 → moderada, 2+ → critica
        severidad = "moderada" if total == 1 else "critica"

        # Separar las inconsistencias que NO son de componentes
        otras_inconsistencias = [
            e for e in extra.get("inconsistencias", [])
            if e.get("estado_origen") != "CONFIRMAR_COMPONENTES"
        ]

        # Construir nueva entrada (simple o consolidada)
        if total == 1:
            nueva_entrada = {
                "estado_origen": "CONFIRMAR_COMPONENTES",
                "mensaje_cliente": f"El cliente indico que le falta: {componente['db']}",
                "severidad": "moderada",
            }
        else:
            nueva_entrada = {
                "estado_origen": "CONFIRMAR_COMPONENTES",
                "mensaje_cliente": "El cliente reporta piezas faltantes en la entrega",
                "severidad": "critica",
                "elementos_faltantes": todos_faltantes,
            }

        inconsistencias_nuevas = otras_inconsistencias + [nueva_entrada]

        # --------------------------------------
        # Recalcular contador
        # --------------------------------------
        contador = dict(extra.get("contador", {"leve": 0, "moderada": 0, "critica": 0, "total": 0}))

        # Si había una entrada previa de componentes, restar su contribución
        if ya_reportados:
            old_sev = "moderada" if len(ya_reportados) == 1 else "critica"
            contador[old_sev] = max(0, contador.get(old_sev, 0) - 1)
            contador["total"] = max(0, contador.get("total", 0) - 1)

        # Sumar la nueva
        contador[severidad] = contador.get(severidad, 0) + 1
        contador["total"]   = contador.get("total", 0) + 1

        contador_ordenado = {
            "leve":     contador.get("leve", 0),
            "moderada": contador.get("moderada", 0),
            "critica":  contador.get("critica", 0),
            "total":    contador.get("total", 0),
        }

        patch_data = {
            "inconsistencias": inconsistencias_nuevas,
            "contador": contador_ordenado,
            "_delete_keys": ["componentes_temp", "faltantes"],
        }

        # --------------------------------------
        # CRITICA (2+ componentes) → escalamiento inmediato
        # --------------------------------------
        if severidad == "critica":
            # Guardar y cerrar inline (no esperar al patch de webhook.py)
            open_or_patch_inconsistencia(
                db=context.db,
                phone=context.phone,
                folio=context.folio,
                session_id=context.session.id,
                patch=patch_data,
            )
            close_open_inconsistencia(
                db=context.db,
                phone=context.phone,
                folio=context.folio,
                session_id=context.session.id,
            )
            return {
                "reply": msg.ESCALAMIENTO_CRITICO,
                "state": ChatState.ACLARACION,
                "buttons": [],
                "patch": None,  # ya guardado arriba
            }

        # MODERADA (1 componente) → preguntar si hay mas
        return {
            "reply": msg.CONFIRMAR_COMPONENTE_FALTANTE.format(componente=componente['label']),
            "state": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "buttons": FLOW[ChatState.COMPONENTES_CONFIRMAR_FALTANTES].get("buttons", []),
            "patch": patch_data,
        }

    elif context.intent in ["FOTO_YA_LO_VI", "negative"]:
        return {
            "reply": msg.FOTO_YA_LO_VI,
            "state": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "buttons": FLOW[ChatState.COMPONENTES_CONFIRMAR_FALTANTES].get("buttons", []),
            "patch": {
                "_delete_keys": ["componentes_temp"],
            }
        }

    return None


# -----------------------------
# DEVOLUCIÓN
# -----------------------------
def handle_devolucion(context):

    # CONFIRMAR DEVOLUCIÓN
    if context.state == ChatState.DEVOLUCION_CONFIRMAR:

        if context.intent == "affirmative" or context.intent == "DEVOLUCION_SI":
            return {
                "reply": msg.PEDIR_MOTIVO_DEVOLUCION,
                "state": ChatState.DEVOLUCION_MOTIVO,
                "buttons": []
            }

        elif context.intent == "negative" or context.intent == "DEVOLUCION_NO":
            try:
                prev_state = ChatState(context.previous_state) if context.previous_state else ChatState.INICIO
            except ValueError:
                prev_state = ChatState.INICIO
                
            ignore_prev_states = {
                ChatState.MENU_AYUDA, 
                ChatState.MENU_DUDA, 
                ChatState.ESPERA, 
                ChatState.FUERA_DE_FLUJO,
                ChatState.CAMBIAR_FOLIO,
                ChatState.CAMBIAR_FOLIO_DEVOLUCION,
                ChatState.CAMBIAR_FOLIO_DESCUENTO,
                ChatState.CAMBIAR_FOLIO_DESCUENTO,
                ChatState.CONFIRMAR_FOLIO_DEVOLUCION,
                ChatState.CONFIRMAR_FOLIO_DESCUENTO,
                ChatState.FINALIZADO
            }
                
            if prev_state in ignore_prev_states:
                # Estaba en el menú, fuera de flujo, o pidiendo folio
                from app.core.states.state_types import get_menu_ayuda_buttons
                return {
                    "reply": msg.AYUDA_ALGO_MAS,
                    "state": ChatState.MENU_AYUDA,
                    "buttons": get_menu_ayuda_buttons(context.previous_state)
                }
            else:
                # Estaba en medio de la verificación
                from app.core.states.state_renderer import render_state
                reply_state, buttons, img = render_state(prev_state, context.session, context.db)
                
                reply = msg.CONTINUAR_VERIFICACION_MENU
                if reply_state:
                    reply += f"\n\n{reply_state}"
                
                return {
                    "reply": reply,
                    "state": prev_state,
                    "buttons": buttons if buttons else FLOW.get(prev_state, {}).get("buttons", []),
                    "image_id": img
                }

    # --------------------------------------
    # CAPTURAR MOTIVO + GUARDAR EN BD
    # --------------------------------------
    if context.state == ChatState.DEVOLUCION_MOTIVO:

        motivo = context.text

        inc = get_open_inconsistencia(
            db=context.db,
            phone=context.phone,
            folio=context.folio,
            session_id=context.session.id
        )

        # SI NO EXISTE → CREAR
        if not inc:
            from app.db.models import Inconsistencias

            inc = Inconsistencias(
                session_id=context.session.id,
                phone=context.phone,
                folio=context.folio,
                estatus="ABIERTA",
                extra_json={},
                devolucion=True,
                motivo_devolucion=motivo
            )

            context.db.add(inc)

        else:
            inc.devolucion = True
            inc.motivo_devolucion = motivo

        # SIEMPRE COMMIT
        context.db.commit()

        return {
            "reply": msg.DEVOLUCION_FINALIZADA,
            "state": ChatState.DEVOLUCION_FINALIZADA,
            "buttons": []
        }

    return None

# -----------------------------
# 4. SALTOS DE FLUJO
# -----------------------------

def handle_flow_skips(context, next_state):
    venta = context.venta

    if not venta:
        return next_state

    if next_state == ChatState.COMPONENTES_FALTANTES:
        inc = get_open_inconsistencia(
            db=context.db,
            phone=context.phone,
            folio=context.folio,
            session_id=context.session.id
        )

        seleccionados = []
        if inc and inc.extra_json:
            seleccionados = _get_componentes_ya_reportados(inc.extra_json)

        disponibles = {
            k: v for k, v in COMPONENTES_MAP.items()
            if v["db"] not in seleccionados
        }

        if not disponibles:
            return ChatState.CONFIRMAR_PAGO_INICIAL

    if next_state == ChatState.CONFIRMAR_COMPONENTES:
        if venta.sku_bitacora_v != "PC-MAXICA":
            return ChatState.CONFIRMAR_ESTADO_PRODUCTO

    if next_state == ChatState.INFO_BENEFICIOS:
        if venta.sku_bitacora_v != "PC-MAXICA":
            return ChatState.INFO_BENEFICIOS2

    return next_state


# -----------------------------
# 5. HANDLER PRINCIPAL
# -----------------------------

def handle_special_cases(context):
    handlers = [
        handle_menu,
        handle_cambiar_folio,
        handle_inconsistencia,
        handle_seleccionar_folio,
        handle_devolucion,  
        handle_componentes,
        handle_verificar_foto,
    ]

    for handler in handlers:
        result = handler(context)
        if result:
            return result

    return None