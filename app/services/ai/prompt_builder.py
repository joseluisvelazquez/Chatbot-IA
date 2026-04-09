from app.core.context.conversation_context import ConversationContext
from app.services.ai.agent_rules import AGENT_RULES
from app.services.ai.agent_messages import AGENT_MESSAGES
from app.core.flow.flow_utils import get_flow_summary
from app.siga.siga_repository import (
    construir_nombre,
    construir_producto,
    construir_pago_inicial,
    obtener_domicilio_por_movimiento,
)
from app.utils.address_formatter import construir_domicilio
from app.utils.date_formatter import formatear_fecha_larga
from app.services.ai.context_loader import load_business_context
from app.core.states.state_types import get_state_type
from app.services.faq.faq_data import FAQ_DATA
from app.utils.product_mapping import get_product_info


# --------------------------------------
# EXTRAER CONTEXTO
# --------------------------------------

def extract_context_info(context: ConversationContext) -> dict:
    venta = context.venta

    return {
        "state": str(context.state),
        "previous_state": str(context.previous_state) if context.previous_state else None,
        "intent": context.intent,
        "folio": context.folio,
        "is_verification": context.is_verification_flow(),

        "venta_info": {
            "producto": getattr(venta, "producto", None) if venta else None,
            "fecha": getattr(venta, "fecha", None) if venta else None,
        }
    }


# --------------------------------------
# BUILD PROMPT
# --------------------------------------

def build_prompt(user_text: str, context: ConversationContext) -> str:
    """
    Construye el prompt para la IA usando:
    - ConversationContext real
    - reglas del agente
    - flujo dinámico
    """

    rules = AGENT_RULES

    # --------------------------------------
    # CONTEXTO TRANSFORMADO
    # --------------------------------------

    ctx = extract_context_info(context)

    if context.state:
        state_type = str(context.state)

    expected_behavior = ""

    stype = get_state_type(context.state)

    if stype == "confirmation":
        expected_behavior = """
    El usuario está respondiendo a una pregunta de confirmación.
    Se espera una respuesta tipo "sí" o "no".
    Si el usuario responde "no", significa que hay un error en la información mostrada.
    """

    elif stype == "information":
        expected_behavior = """
    El usuario está recibiendo información.
    Si responde con dudas o confusión, debes aclarar la información de forma simple.
    """

    elif stype == "inconsistency":
        expected_behavior = """
    El usuario está reportando una inconsistencia.
    Debes enfocarte en entender la corrección o el error que menciona.
    """

    # --------------------------------------
    # MENSAJES
    # --------------------------------------

    escalation_msg = AGENT_MESSAGES["escalation"]["default"]
    out_of_scope_msg = AGENT_MESSAGES["out_of_scope"]["default"]

    # --------------------------------------
    # PROMPT FINAL
    # --------------------------------------
    
    business_context = load_business_context()

    faq_lines = []
    for item in FAQ_DATA:
        kws = ", ".join(item["keywords"][:4])  # tomamos las primeras 4 como ejemplo
        resp = item["response"]
        faq_lines.append(f"- Si pregunta sobre: {kws}\n  RESPUESTA OFICIAL: {resp}\n")
    faq_context = "\n".join(faq_lines)

    prompt = f"""
Eres {rules["agent"]["name"]}, asistente virtual de {rules["agent"]["company"]}.

Tu función es:
{rules["agent"]["role"]}

--------------------------------------
INFORMACIÓN DE LA EMPRESA (CONOCIMIENTO BASE)
--------------------------------------
{business_context}

--------------------------------------
PREGUNTAS FRECUENTES (USAR RESPUESTA OFICIAL)
--------------------------------------
Si el mensaje del cliente aborda alguno de los siguientes temas, DEBES usar la respuesta oficial indicada de manera concisa:

{faq_context}
--------------------------------------
REGLAS IMPORTANTES
--------------------------------------

- Solo puedes responder sobre: {", ".join(rules["scope"]["allowed_topics"])}
- No inventes información bajo ninguna circunstancia
- Si no tienes suficiente información, debes escalar usando EXACTAMENTE este mensaje:
  "{escalation_msg}"
- Si el tema está fuera del alcance, responde:
  "{out_of_scope_msg}"

--------------------------------------
CONTEXTO ACTUAL
--------------------------------------

Estado actual: {ctx["state"]}
Estado previo: {ctx["previous_state"]}
Intent detectado: {ctx["intent"]}
Folio: {ctx["folio"]}
En verificación: {ctx["is_verification"]}

Producto: {ctx["venta_info"]["producto"]}
Fecha: {ctx["venta_info"]["fecha"]}

--------------------------------------
EXPECTATIVA SEGÚN ESTADO
--------------------------------------

{expected_behavior}

--------------------------------------
MENSAJE DEL CLIENTE
--------------------------------------

{user_text}

--------------------------------------
INSTRUCCIONES DE RESPUESTA
--------------------------------------

- Responde de forma clara, breve y fácil de entender
- Usa tono amigable y semi formal
- Usa lenguaje sencillo
- No generes respuestas largas innecesarias
- NO hagas preguntas al usuario
- NO solicites confirmaciones
- SOLO responde la duda del usuario
- NO cambies el flujo
- NO sugieras acciones
- Si el usuario está en verificación, NO abandones el flujo
- Responde en UNA sola idea
- Máximo una oración corta
- NO uses frases introductorias como "claro", "con gusto", "te explico"
- NO repitas información
- NO agregues contexto adicional innecesario
"""

    return prompt.strip()


def build_inconsistency_prompt(user_text: str, context: ConversationContext) -> str:
    """
    Prompt especializado para analizar inconsistencias en estados de confirmación.
    La IA debe responder ÚNICAMENTE en JSON válido.
    """

    venta = context.venta
    db = context.db
    session = context.session

    # -------------------------
    # MAPEO ESTADO -> CONFIG
    # -------------------------
    STATE_CONFIG = {
        "CONFIRMAR_NOMBRE": {
            "campo": "nombre",
            "pregunta": "¿El nombre completo del cliente es correcto?",
        },
        "CONFIRMAR_DOMICILIO": {
            "campo": "domicilio",
            "pregunta": "¿El domicilio mostrado es correcto?",
        },
        "CONFIRMAR_FECHA": {
            "campo": "fecha",
            "pregunta": "¿La fecha mostrada de la venta/contrato es correcta?",
        },
        "CONFIRMAR_PRODUCTO": {
            "campo": "producto",
            "pregunta": "¿El producto adquirido mostrado es correcto?",
        },
        "CONFIRMAR_ESTADO_PRODUCTO": {
            "campo": "estado_producto",
            "pregunta": "¿El cliente confirmó que el producto está en buen estado?",
        },
        "CONFIRMAR_PAGO_INICIAL": {
            "campo": "pago_inicial",
            "pregunta": "¿El monto del pago inicial mostrado es correcto?",
        },
    }

    current_state = str(context.state).replace("ChatState.", "")
    target_state = current_state
    
    # Si estamos en estado de INCONSISTENCIA, inferir el campo basándonos en el estado previo
    if target_state == "INCONSISTENCIA" and context.previous_state:
        target_state = str(context.previous_state).replace("ChatState.", "")

    state_info = STATE_CONFIG.get(
        target_state,
        {
            "campo": "otro",
            "pregunta": "Analiza la inconsistencia reportada por el cliente.",
        },
    )

    campo = state_info["campo"]
    pregunta_actual = state_info["pregunta"]

    # -------------------------
    # VALOR ESPERADO DEL SISTEMA
    # -------------------------
    valor_sistema = "No disponible"

    try:
        if campo == "nombre" and venta:
            valor_sistema = construir_nombre(venta)

        elif campo == "domicilio" and venta and db:
            domicilio = obtener_domicilio_por_movimiento(db, venta.id_movimiento_bv)
            valor_sistema = construir_domicilio(domicilio) if domicilio else "No disponible"

        elif campo == "fecha" and venta:
            if venta.fecha_venta:
                valor_sistema = formatear_fecha_larga(venta.fecha_venta)

        elif campo == "producto" and venta:
            info = get_product_info(venta.sku_bitacora_v)
            valor_sistema = info["nombre_amigable"]

        elif campo == "estado_producto":
            valor_sistema = "Producto en buen estado"

        elif campo == "pago_inicial" and venta:
            valor_sistema = construir_pago_inicial(venta)

    except Exception:
        valor_sistema = "No disponible"

    # -------------------------
    # REGLAS PARA TRATAR INCONSISTENCIAS
    # -------------------------

    detalle_campo = "- Analiza el mensaje reportado por el cliente de forma genérica."

    if campo == "nombre":
        detalle_campo = """
    - critica: Cuando el cliente proporciona un nombre completo el cual más de 2 elementos son diferentes al que se le mostró ya sean nombres o apellidos, o bien indica que desconoce al titular. Se interpreta como que el cliente es una persona distinta o posible suplantación.
    - moderada: Cuando el cliente corrige uno de los nombres o uno de los apellidos, pero por lo menos 3 elementos del nombre completo siguen siendo los mismos, se debe interpretar como que fue un error al registrar la venta.
    - leve: Solo corrige la ortografía o acentos, se debe interpretar como que fue un error de captura de dedo.
    """

    elif campo == "domicilio":
        detalle_campo = """
    - critica: Cuando la dirección proporcionada por el cliente cambia más de 2 elementos de la dirección mostrada o indica que ya no vive ahí. Se interpreta como un riesgo de evasión al cambiar dónde lo pueden ubicar.
    - moderada: Cuando el cliente corrige solo uno de los elementos de la dirección mostrada se debe interpretar como que fue un error del vendedor al registrar la venta.
    - leve: Solo corrige ortografía de la dirección mostrada, se debe interpretar como que fue un error de captura de dedo.
    """

    elif campo == "fecha":
        detalle_campo = """
    - critica: Cuando la fecha que proporciona el cliente tiene un desfase con la fecha mostrada de más de 3 días o dice que no firmó nada y desconoce la fecha. Se interpreta como un intento de aprovecharse cambiando la fecha para tener más tiempo para pagar.
    - moderada: Cuando la fecha que indica el cliente tiene un desfase de 1 o 2 días con la fecha mostrada, se interpreta como que fue un malentendido entre el día que se firmó el contrato y el día que se registró en el sistema.
    """

    elif campo == "producto":
        detalle_campo = """
    - critica: Cuando el cliente niega haber comprado un producto. Se interpreta como un intento de evasión no aceptando lo que compró.
    - moderada: Cuando el producto proporcionado por el cliente está dentro de los productos que se venden pero es diferente al mostrado. Se interpreta como un error al registrar la venta.
    """

    elif campo == "estado_producto":
        detalle_campo = """
    - critica: El daño reportado hace que el equipo no se pueda utilizar.
    - moderada: El equipo funciona, pero tiene daños estéticos.
    - leve: Quejas sobre la limpieza, empaque superficial, o detalles que no afectan en absoluto la estética ni el funcionamiento.
    """

    elif campo == "pago_inicial":
        detalle_campo = """
    - critica: Si la cantidad proporcionada por el cliente es diferente a la cantidad mostrada. Se interpreta como un error al registrar la venta.
    """

    # -------------------------
    # PROMPT FINAL (COMPACTO)
    # -------------------------
    prompt = f"""Clasifica la severidad de esta inconsistencia en un proceso de verificación de venta.

Campo evaluado: {campo}
Valor esperado: {valor_sistema}
Mensaje del cliente: {user_text}

Criterios:
{detalle_campo}

Responde SOLO con JSON, sin explicaciones:
{{"severidad": "leve"|"moderada"|"critica"}}"""

    return prompt.strip()