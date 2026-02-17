import re
from app.core.states import ChatState

INTENT_KEYWORDS = {
    "affirmative": ["sí", "si", "ok", "vale", "adelante", "correcto"],
    "negative": ["no", "nop", "incorrecto"],
    "later": ["luego", "después", "mas tarde", "más tarde"],
    "doubt": ["duda", "dudas", "no entiendo", "no entiendo bien"],
    "human": ["llamar", "asesor", "persona", "hablar"],
}

# Para binario, conviene tokenizar y contar "si/no" como palabras (no como substrings)
BIN_AFF = {"si", "sí"}
BIN_NEG = {"no"}


def detect_intent(text: str, state: ChatState | None = None) -> str:
    text_l = text.lower()

    # 1) Tokenizar (palabras) para binario
    words = re.findall(r"[a-záéíóúñ]+", text_l)

    pos = sum(w in BIN_AFF for w in words)
    neg = sum(w in BIN_NEG for w in words)

    # Si hay mezcla binaria, decide por mayoría; empate -> ambiguous
    if pos or neg:
        if pos > neg:
            return "affirmative"
        if neg > pos:
            return "negative"
        return "ambiguous"

    # 2) Si NO hay binario, aplica intents generales (por substring como ya hacías)
    detected = set()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k in text_l for k in keywords):
            detected.add(intent)

    if not detected:
        return "other"

    # prioridad SOLO para generales
    priority_general = ["human", "doubt", "later"]
    for intent in priority_general:
        if intent in detected:
            return intent

    # fallback
    return next(iter(detected))
