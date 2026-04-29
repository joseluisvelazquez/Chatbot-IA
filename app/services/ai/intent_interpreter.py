from app.services.ai.ai_service import generate_ai_response, _extract_json
from app.core.context.conversation_context import ConversationContext
from app.core.states.state_types import get_state_type
from app.core.states.states import ChatState
import json


VALID_INTENTS = {
    "affirmative",
    "negative",
    "doubt",
    "human",
    "call",
    "later",
    "other",
    "devolucion",
    "descuento",
}

def is_doubt(text: str) -> bool:
    text = text.lower()

    doubt_keywords = [
        "qué es",
        "que es",
        "cómo",
        "como",
        "por qué",
        "porque",
        "no entiendo",
        "explícame",
        "explicame",
        "duda",
        "qué significa",
        "significa",
    ]

    return any(k in text for k in doubt_keywords)

def should_use_ai(text: str, detected_intent: str, state=None) -> bool:
    """
    Decide si vale la pena usar IA considerando:
    - texto
    - intención
    - estado del flujo
    """

    if state == ChatState.MENU_DUDA:
        return True
    

    if not text:
        return False

    text = text.strip().lower()
    words = text.split()
    word_count = len(words)

    # CONTEXTO DEL ESTADO
    state_type = get_state_type(state) if state else None

    
    # CONFIRMATION → NO IA
    if state_type == "confirmation":
        return word_count >= 2  # Permitir IA si parece una corrección o detalle

    # INCONSISTENCIA → SIEMPRE IA
    if state_type == "inconsistency":
        return True

    # INFORMATION → IA PERMITIDA
    if state_type == "information":
        if word_count >= 2:
            return True


    # HARD BLOCK (NUNCA IA)
    if text in {"si", "sí", "no", "ok", "vale"}:
        return False


    # INTENTS CLAROS
    if detected_intent in {"affirmative", "negative", "call", "human", "later"}:
        if word_count < 4:
            return False


    # INTENT DÉBIL
    if detected_intent in ("other", "ambiguous", None):
        return True


    # PALABRAS CLAVE
    keywords = ["pero", "aunque", "creo", "pienso", "no entiendo", "duda"]

    if any(k in text for k in keywords):
        return True

    # MENSAJE LARGO
    if word_count >= 6:
        return True

    return False

def interpret_intent_with_ai(
    user_text: str,
    context: ConversationContext,
    session=None
) -> dict | None:
    """
    Interpreta texto libre usando IA y devuelve:
    {
        intent: str,
        confidence: str (low | medium | high)
    }
    """

    estado_origen = context.state if context else "No especificado"

    prompt = f"""
Eres un sistema que clasifica mensajes de usuarios en un chatbot de verificación.

Debes responder ÚNICAMENTE en JSON válido.

--------------------------------------
INTENTS POSIBLES
--------------------------------------

- affirmative
- negative
- doubt
- human
- call
- later
- other
- devolucion
- descuento

--------------------------------------
CONTEXTO
--------------------------------------
Estado actual del usuario: {estado_origen}

--------------------------------------
MENSAJE DEL USUARIO
--------------------------------------

{user_text}

--------------------------------------
REGLAS
--------------------------------------

- REGLA ESTRICTA: Si el "Estado actual" es una confirmación (ej: CONFIRMAR_DOMICILIO, CONFIRMAR_FECHA, CONFIRMAR_PAGO_INICIAL, etc.) y el usuario proporciona un dato diferente, un número, o una corrección (ej: "mi numero de casa es 32", "fue el 10", "fue por 600"), DEBES clasificarlo obligatoriamente como "negative".
- "sí", "correcto", "todo bien" → affirmative
- "no", "está mal", "yo pagué 550" → negative
- preguntas → doubt
- quiere asesor → human
- quiere llamada → call
- quiere después → later
- quiere regresar equipo, cancelar compra → devolucion
- pregunta por su cuenta, cómo se aplica su descuento → descuento

--------------------------------------
CONFIDENCE
--------------------------------------

- high → muy claro
- medium → probable
- low → incierto

--------------------------------------
RESPUESTA (JSON)
--------------------------------------

Ejemplo:
{{
  "intent": "negative",
  "confidence": "high"
}}
"""

    try:
        raw = generate_ai_response(prompt, context, session=session,mode="intent" )

        if not raw:
            return None

        data = _extract_json(raw)

        if data is None or not isinstance(data, dict):
            return None
        
        intent = data.get("intent")
        confidence = data.get("confidence")

        # validar campos obligatorios
        if not intent:
            return None

        # normalizar valores
        intent = str(intent).lower().strip()

        if intent not in VALID_INTENTS:
            return None

        if confidence:
            confidence = str(confidence).lower().strip()
        else:
            confidence = "low"

        return {
            "intent": intent,
            "confidence": confidence
        }    
    
    except Exception:
        return None
    

def detect_frustration(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    frustration_keywords = [
        "no entiendo",
        "no entendí",
        "no me queda claro",
        "no me quedó claro",
        "explícame",
        "explicame",
        "otra vez",
        "no es eso",
        "eso no",
        "no funciona",
        "no sirve",
    ]

    return any(k in text for k in frustration_keywords)