import re
import time
import json
import logging

try:
    from google import genai
except ImportError:
    genai = None

from app.services.ai.prompt_builder import build_inconsistency_prompt
from app.config.settings import settings
from app.services.ai.prompt_builder import build_faq_identification_prompt, build_prompt
from app.core.context.conversation_context import ConversationContext
from app.services.ai.agent_messages import AGENT_MESSAGES

logger = logging.getLogger(__name__)
_client = None
_gemini_cooldown_until = 0.0
GEMINI_MODEL = "gemini-2.5-flash-lite"


def _get_client():
    global _client
    if genai is None:
        logger.warning("gemini_client_unavailable")
        return None
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _gemini_error_meta(exc: Exception) -> dict:
    meta = {"error_type": exc.__class__.__name__}
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if value is not None:
            meta[attr] = value
    return meta


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or "quota" in text
        or getattr(exc, "code", None) == 429
        or getattr(exc, "status_code", None) == 429
    )


def generate_raw_ai_response(prompt: str, *, task: str = "raw", model: str = GEMINI_MODEL) -> str | None:
    """
    Devuelve texto crudo de Gemini sin formatearlo.
    Úsalo para JSON de intención, análisis y clasificación FAQ.
    """
    global _gemini_cooldown_until

    now = time.time()
    if now < _gemini_cooldown_until:
        logger.info(
            "gemini_request_skipped_cooldown",
            extra={"task": task, "cooldown_seconds": round(_gemini_cooldown_until - now, 1)},
        )
        return None

    client = _get_client()
    if client is None:
        return None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            response_text = response.text.strip() if response and response.text else None
            if response_text:
                return response_text
        except Exception as exc:
            if _is_quota_error(exc):
                _gemini_cooldown_until = time.time() + 60
                logger.warning(
                    "gemini_quota_exhausted",
                    extra={
                        "task": task,
                        "cooldown_seconds": 60,
                        **_gemini_error_meta(exc),
                    },
                )
                return None

            log = logger.warning if attempt == MAX_RETRIES - 1 else logger.info
            log(
                "gemini_raw_response_failed",
                extra={
                    "task": task,
                    "attempt": attempt + 1,
                    **_gemini_error_meta(exc),
                },
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)

    return None

def identify_faq_id(user_text: str) -> int | None:
    """
    Usa IA para identificar el ID de la FAQ más relevante para el texto del usuario.
    Retorna el índice del item en FAQ_DATA o None si no hay match.
    """
    prompt = build_faq_identification_prompt(user_text)
    client = _get_client()
    if client is None:
        return None

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
            logger.warning("gemini_faq_identification_failed", extra={"error_type": e.__class__.__name__})
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_DELAY_SECONDS)

    return None

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1
MAX_AGENT_ATTEMPTS = 2


def identify_faq_id(user_text: str) -> int | None:
    """
    Usa IA para identificar el ID de la FAQ mas relevante sin modificar la salida.
    """
    prompt = build_faq_identification_prompt(user_text)
    res_text = generate_raw_ai_response(prompt, task="faq_identification")
    if not res_text:
        logger.warning("gemini_faq_identification_failed", extra={"reason": "empty_response"})
        return None

    res_text = res_text.strip().upper()
    if "NONE" in res_text:
        return None

    match = re.search(r"(\d+)", res_text)
    if match:
        return int(match.group(1))

    return None


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
            ai_attempts = getattr(session, "ai_intent_attempts", 0) or 0
        elif mode == "inconsistency":
            ai_attempts = getattr(session, "ai_inconsistency_attempts", 0) or 0
        else:
            ai_attempts = getattr(session, "ai_response_attempts", 0) or 0
    else:
        ai_attempts = 0

    if ai_attempts >= MAX_AGENT_ATTEMPTS:
        return None

    prompt = build_prompt(user_text, context)
    client = _get_client()
    if client is None:
        return None

    for attempt in range(MAX_RETRIES):
        try:
            #print("🚀 ENTRANDO A GEMINI...")

            response_text = generate_raw_ai_response(prompt, task=mode, model=GEMINI_MODEL)

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

                if len(response_text) > 800:
                    # Cortar en el último espacio antes del límite para no romper palabras
                    corte = response_text[:800].rfind(" ")
                    if corte != -1:
                        response_text = response_text[:corte]
                    else:
                        response_text = response_text[:800]

                # --------------------------------------
                # EVITAR PREGUNTAS
                # --------------------------------------

                if "?" in response_text:
                    # En lugar de cortar abruptamente, simplemente quitamos las líneas finales que sean preguntas
                    lines = response_text.split('\n')
                    clean_lines = [line for line in lines if "?" not in line]
                    if clean_lines:
                        response_text = "\n".join(clean_lines).strip()
                    else:
                        # Si todo era pregunta, lo dejamos (para no devolver vacío)
                        pass

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
            logger.warning("gemini_response_failed", extra=_gemini_error_meta(e))

            if attempt == MAX_RETRIES - 1:
                return None

            time.sleep(RETRY_DELAY_SECONDS)

    logger.warning("gemini_response_failed", extra={"reason": "empty_response"})
    return None


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
    client = _get_client()
    if client is None:
        return _fallback_inconsistency(user_text, context)

    raw_response = None

    # --------------------------------------
    # LLAMADA A GEMINI
    # --------------------------------------

    for attempt in range(MAX_RETRIES):
        try:
            raw_response = generate_raw_ai_response(prompt, task="inconsistency", model=GEMINI_MODEL)

            if raw_response:
                break

        except Exception as e:
            logger.warning("gemini_inconsistency_failed", extra=_gemini_error_meta(e))

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
        logger.warning("gemini_inconsistency_json_parse_failed")
        return _fallback_inconsistency(user_text, context)

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
