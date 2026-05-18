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
from app.utils.product_mapping import get_product_info_for_sale


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

        if str(context.state).endswith("INFO_COMPROBANTE_ACCESO"):
            expected_behavior += """
    El usuario esta viendo los datos para enviar comprobantes.
    Si pregunta por comprobantes, debes indicar que se envian en https://mxcomp.mx/ usando el numero de cuenta y codigo de cliente mostrados en la verificacion.
    Nunca digas que debe adjuntar el comprobante en este chat.
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
- Si no tienes suficiente informacion para una duda normal del flujo, responde que no tienes ese dato en este momento.
- Usa el mensaje de escalamiento EXACTO solo si el cliente pide asesor/llamada o si el caso requiere revision humana:
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
            info = get_product_info_for_sale(venta)
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
    - critica: Cuando la fecha que proporciona el cliente es diferente a la fecha mostrada o dice que no firmó nada y desconoce la fecha.
    """

    elif campo == "producto":
        detalle_campo = """
    - critica: Cuando el cliente indica que compró cualquier otro producto diferente al mostrado o niega haber comprado el producto.
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

def build_faq_identification_prompt(user_text: str) -> str:
    """
    Prompt especializado para identificar si una duda coincide con una FAQ existente.
    """
    faq_list = []
    for i, item in enumerate(FAQ_DATA):
        kws = ", ".join(item["keywords"])
        faq_list.append(f"ID {i}: {kws}")

    faqs_str = "\n".join(faq_list)

    prompt = f"""
Actúa como un clasificador de preguntas frecuentes (FAQ).
Tu objetivo es determinar si el mensaje del usuario coincide semánticamente con alguna de las categorías de FAQ listadas abajo.

LISTA DE FAQs:
{faqs_str}

MENSAJE DEL USUARIO:
"{user_text}"

INSTRUCCIONES:
1. Analiza si el mensaje del usuario es una pregunta o duda que encaja en alguna de las categorías.
2. Considera sinónimos y variaciones (ej. "oxxos" es igual a "oxxo", "cambio el costo" es igual a "cambia el precio").
3. Si hay un match claro, responde ÚNICAMENTE con el número del ID (ej: 0).
4. Si NO hay un match o el mensaje es ambiguo, responde ÚNICAMENTE: NONE.
5. NO des explicaciones ni uses etiquetas.

ID:"""
    return prompt.strip()
