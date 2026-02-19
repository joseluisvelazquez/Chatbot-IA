import re
from app.core.states import ChatState

INTENT_KEYWORDS = {
    "affirmative": ["ok", "vale", "adelante", "correcto"],
    "negative": ["nop", "incorrecto"],
    "later": ["luego", "después", "mas tarde", "más tarde"],
    "doubt": ["duda", "dudas", "no entiendo", "no entiendo bien"],
    "human": ["llamar", "asesor", "persona", "hablar"],
}

BIN_AFF = {"si", "sí"}
BIN_NEG = {"no"}

CRITICAL_PRIORITY = ["human", "doubt"]


def detect_intent(text: str, state: ChatState | None = None) -> str:
    text_l = text.lower().strip()

    # -------------------------------------------------
    # 0️⃣ Inicio formal obligatorio
    # -------------------------------------------------
    folio_pattern = r"folio\s*es\s*:\s*(\w+)"
    if re.search(folio_pattern, text_l):
        return "start_verification"

    # -------------------------------------------------
    # 1️⃣ Intenciones críticas primero (NO binarias)
    # -------------------------------------------------
    for intent in CRITICAL_PRIORITY:
        for k in INTENT_KEYWORDS[intent]:
            if k in text_l:
                return intent

    # -------------------------------------------------
    # 2️⃣ Binario puro
    # -------------------------------------------------
    words = re.findall(r"[a-záéíóúñ]+", text_l)

    pos = sum(w in BIN_AFF for w in words)
    neg = sum(w in BIN_NEG for w in words)

    if pos or neg:
        if pos > neg:
            return "affirmative"
        if neg > pos:
            return "negative"
        return "ambiguous"

    # -------------------------------------------------
    # 3️⃣ Intenciones generales
    # -------------------------------------------------
    for intent, keywords in INTENT_KEYWORDS.items():
        if intent in CRITICAL_PRIORITY:
            continue
        if any(k in text_l for k in keywords):
            return intent

    return "other"
