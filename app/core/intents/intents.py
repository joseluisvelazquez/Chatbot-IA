import re
import unicodedata
from app.core.states.states import ChatState
from app.utils.folio_parser import extraer_folio_explicito

# -------------------------------------------------
# Catálogo de intenciones
# -------------------------------------------------

# Flujo normal
INTENTS_FLOW = {
    "affirmative",   # sí
    "negative",      # no
    "later",         # después
}

# Control / acciones del usuario
INTENTS_CONTROL = {
    "human",              # quiere asesor (chat)
    "call",               # quiere llamada
    "start_verification", # inicio con folio
    "resume",             # reanudar o continuar
}

# Sociales
INTENTS_SOCIAL = {
    "greeting",
    "thanks",
}

# IA / fallback
INTENTS_AI = {
    "doubt",
    "ambiguous",
    "other",
}


# -------------------------------------------------
# Normalización de texto
# -------------------------------------------------

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# -------------------------------------------------
# Palabras clave
# -------------------------------------------------

INTENT_KEYWORDS = {

    # -------------------------
    # Sociales
    # -------------------------
    "greeting": [
        "buenas",
        "buen dia",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "que tal"
    ],

    "thanks": [
        "gracias",
        "todo bien",
        "ya nada",
        "es todo",
        "ninguna duda",
        "sin dudas",
        "muy amable",
        "no gracias"
    ],

    # -------------------------
    # Flujo
    # -------------------------
    "affirmative": [
        "ok",
        "vale",
        "correcto",
        "de acuerdo",
        "esta bien",
        "perfecto",
        "claro",
        "claro que si",
        "sip"
    ],

    "negative": [
        "incorrecto",
        "esta mal",
        "no coincide",
        "no es correcto",
    ],

    "later": [
        "luego",
        "despues",
        "mas tarde",
        "en otro momento",
    ],

    # -------------------------
    # IA
    # -------------------------
    "doubt": [
        "duda",
        "dudas",
        "pregunta",
        "preguntas",
        "hacer una pregunta",
        "no entiendo",
        "no entiendo bien",
        "tengo duda",
        "tengo dudas",
        "tengo una duda",
        "explicame",
        "explicar",
    ],

    # -------------------------
    # HUMANO (chat)
    # -------------------------
    "human": [
        "asesor",
        "persona",
        "hablar con alguien",
        "quiero hablar con alguien",
        "comunicarme con alguien",
        "soporte",
        "ayuda humana",
    ],

    # -------------------------
    # LLAMADA (separado)
    # -------------------------
    "call": [
        "llamar",
        "llamada",
        "marcar",
        "que me llamen",
        "puedes llamarme",
        "agendar llamada",
    ],

    "resume": [
        "continuar",
        "iniciar verificacion",
        "reanudar",
        "seguir",
        "listo",
        "avanza",
        "avanzar",
        "proseguir",
        "continua"
    ]
}


# -------------------------------------------------
# Respuestas binarias simples
# -------------------------------------------------

BIN_AFFIRMATIVE = {
    "si",
    "claro",
}

BIN_NEGATIVE = {
    "no",
}


# -------------------------------------------------
# Prioridad de detección
# -------------------------------------------------

# Orden importa mucho
CRITICAL_PRIORITY = [
    "call",     #  primero llamada
    "human",    # luego asesor
    "doubt",    # luego dudas
]


# -------------------------------------------------
# Función principal
# -------------------------------------------------

def detect_intent(text: str, state: ChatState | None = None):

    if not text:
        return "other", None

    text_l = normalize_text(text)

    # -------------------------------------------------
    # Detectar inicio con folio
    # -------------------------------------------------

    folio = extraer_folio_explicito(text_l)
    if folio:
        return "start_verification", folio

    # -------------------------------------------------
    # Prioridad crítica y preguntas
    # -------------------------------------------------

    if "?" in text or "¿" in text:
        return "doubt", None

    for intent in CRITICAL_PRIORITY:
        for keyword in INTENT_KEYWORDS[intent]:
            if keyword in text_l:
                return intent, None

    # -------------------------------------------------
    # Saludos y Agradecimientos
    # -------------------------------------------------

    for keyword in INTENT_KEYWORDS["greeting"]:
        if keyword in text_l:
            return "greeting", None

    for keyword in INTENT_KEYWORDS["thanks"]:
        if keyword in text_l:
            return "thanks", None

    # -------------------------------------------------
    # Binario simple
    # -------------------------------------------------

    words = re.findall(r"[a-z0-9]+", text_l)

    pos = sum(w in BIN_AFFIRMATIVE for w in words)
    neg = sum(w in BIN_NEGATIVE for w in words)

    if pos or neg:

        if pos > neg:
            return "affirmative", None

        if neg > pos:
            return "negative", None

        return "ambiguous", None

    # -------------------------------------------------
    # Keywords generales
    # -------------------------------------------------

    for intent, keywords in INTENT_KEYWORDS.items():

        if intent in CRITICAL_PRIORITY or intent == "greeting":
            continue

        for keyword in keywords:
            if keyword in text_l:
                return intent, None

    # -------------------------------------------------
    # Fallback
    # -------------------------------------------------

    return "other", None
