import re
import time
import json
from google import genai
from app.services.ai.prompt_builder import build_inconsistency_prompt
from app.config.settings import settings
from app.services.ai.prompt_builder import build_faq_identification_prompt, build_prompt
from app.core.context.conversation_context import ConversationContext
from app.services.ai.agent_messages import AGENT_MESSAGES

def identify_faq_id(user_text: str) -> int | None:
    """
    Usa IA para identificar el ID de la FAQ más relevante para el texto del usuario.
    Retorna el índice del item en FAQ_DATA o None si no hay match.
    """
    prompt = build_faq_identification_prompt(user_text)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite", # Usamos flash lite para rapidez
                contents=prompt,
            )

            res_text = response.text.strip().upper() if response and response.text else "NONE"

            if "NONE" in res_text:
                return None
            
            # Extraer solo los dígitos
            match = re.search(r"(\d+)", res_text)
            if match:
                return int(match.group(1))

        except Exception as e:
            print("❌ ERROR GEMINI (FAQ identity):", str(e))
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_SECONDS)

    return None

client = genai.Client(api_key=settings.GEMINI_API_KEY)

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1
MAX_AGENT_ATTEMPTS = 2


def generate_ai_response(
    user_text: str,
    context: ConversationContext,
    session=None,
    mode: str = "response"
) -> str:
    """
    Genera respuesta usando Gemini con:
    - retry de 2 intentos
    - control de intentos del agente
    """

    if session:
        if mode == "intent":
            ai_attempts = session.ai_intent_attempts or 0
        elif mode == "inconsistency":
            ai_attempts = session.ai_inconsistency_attempts or 0
        else:
            ai_attempts = session.ai_response_attempts or 0
    else:
        ai_attempts = 0

    if ai_attempts >= MAX_AGENT_ATTEMPTS:
        return None

    prompt = build_prompt(user_text, context)

    for attempt in range(MAX_RETRIES):
        try:
            #print("🚀 ENTRANDO A GEMINI...")

            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
            )

            response_text = response.text.strip() if response and response.text else None

            if response_text:
                # --------------------------------------
                # LIMPIEZA BASE
                # --------------------------------------

                response_text = response_text.strip()

                # --------------------------------------
                # ELIMINAR FRASES INÚTILES
                # --------------------------------------

                frases_basura = [
                    "claro,",
                    "claro.",
                    "con gusto,",
                    "con gusto.",
                    "te explico,",
                    "te explico.",
                    "por supuesto,",
                    "por supuesto.",
                ]

                lower_text = response_text.lower()

                for frase in frases_basura:
                    if lower_text.startswith(frase):
                        response_text = response_text[len(frase):].strip()
                        break

                # --------------------------------------
                # LIMITAR LONGITUD
                # --------------------------------------

                if len(response_text) > 250:
                    response_text = response_text[:250]

                # --------------------------------------
                # SOLO PRIMERA IDEA (CLAVE)
                # --------------------------------------

                if not response_text.startswith("{"):
                    for sep in [". ", "\n"]:
                        if sep in response_text:
                            response_text = response_text.split(sep)[0].strip()
                            break

                # --------------------------------------
                # EVITAR PREGUNTAS
                # --------------------------------------

                if "?" in response_text:
                    response_text = response_text.split("?")[0].strip()

                # --------------------------------------
                # ASEGURAR FORMATO FINAL
                # --------------------------------------

                # evitar respuestas vacías
                if not response_text:
                    response_text = "No se pudo obtener una respuesta clara."

                # asegurar punto final
                if not response_text.endswith("."):
                    response_text += "."

                # capitalizar primera letra
                response_text = response_text[0].upper() + response_text[1:]

                if session:
                    if mode == "intent":
                        session.ai_intent_attempts = ai_attempts + 1
                    elif mode == "inconsistency":
                        session.ai_inconsistency_attempts = ai_attempts + 1
                  
                return response_text

            #print("⚠️ Gemini respondió vacío")

        except Exception as e:
            print("❌ ERROR GEMINI:", str(e))

            if attempt == MAX_RETRIES - 1:
                return AGENT_MESSAGES["escalation"]["default"]

            time.sleep(RETRY_DELAY_SECONDS)

    return AGENT_MESSAGES["escalation"]["default"]


# --------------------------------------
# ANALYZE INCONSISTENCY
# --------------------------------------

def analyze_inconsistency(
    user_text: str,
    context: ConversationContext,
    session=None
) -> dict:
    """
    Analiza inconsistencias usando IA y retorna JSON limpio y validado.
    """

    prompt = build_inconsistency_prompt(user_text, context)

    raw_response = None

    # --------------------------------------
    # LLAMADA A GEMINI
    # --------------------------------------

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
            )

            raw_response = response.text.strip() if response and response.text else None

            if raw_response:
                break

        except Exception as e:
            print("❌ ERROR GEMINI (inconsistencia):", str(e))

            if attempt == MAX_RETRIES - 1:
                return _fallback_inconsistency(user_text, context)

            time.sleep(RETRY_DELAY_SECONDS)

    if not raw_response:
        return _fallback_inconsistency(user_text, context)

    # --------------------------------------
    # PARSE JSON (ROBUSTO)
    # --------------------------------------

    data = _extract_json(raw_response)

    if data is None:
        print("⚠️ IA: no se pudo extraer JSON → fallback crítica")
        return _fallback_inconsistency(user_text, context)

    print(f"🤖 IA clasificó: {data.get('severidad', '?')}")

    return _validate_inconsistency(data, context, user_text)


# --------------------------------------
# EXTRACCIÓN ROBUSTA DE JSON
# --------------------------------------

def _extract_json(text: str) -> dict | None:
    """
    Extrae el primer objeto JSON válido de una respuesta de texto libre.
    Soporta JSON crudo, bloques ```json``` y texto con razonamiento alrededor.
    """
    if not text:
        return None

    text = text.strip()

    # 1) Intentar parsear directamente
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) Buscar bloque ```json ... ```
    md_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except Exception:
            pass

    # 3) Buscar cualquier objeto JSON { ... } en el texto
    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except Exception:
            pass

    return None


# --------------------------------------
# VALIDACIÓN
# --------------------------------------

def _validate_inconsistency(data: dict, context: ConversationContext, user_text: str) -> dict:

    VALID_SEVERITY = {"leve", "moderada", "critica"}

    # Resolver estado real: si estamos en INCONSISTENCIA, usar el anterior
    current_state = str(context.state).replace("ChatState.", "")
    if current_state == "INCONSISTENCIA" and context.previous_state:
        estado_real = str(context.previous_state).replace("ChatState.", "")
    else:
        estado_real = current_state

    severidad = data.get("severidad", "moderada")
    if severidad not in VALID_SEVERITY:
        severidad = "moderada"

    return {
        "estado_origen": estado_real,
        "mensaje_cliente": user_text,
        "severidad": severidad,
    }


# --------------------------------------
# FALLBACK
# --------------------------------------

def _fallback_inconsistency(user_text: str, context: ConversationContext) -> dict:
    """
    Fallback cuando la IA falla: escala como crítica.
    """
    current_state = str(context.state).replace("ChatState.", "")
    if current_state == "INCONSISTENCIA" and context.previous_state:
        estado_real = str(context.previous_state).replace("ChatState.", "")
    else:
        estado_real = current_state

    return {
        "estado_origen": estado_real,
        "mensaje_cliente": user_text,
        "severidad": "critica",
    }