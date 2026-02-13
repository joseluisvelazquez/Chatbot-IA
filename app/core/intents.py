import re
from app.core.states import ChatState

INTENT_PRIORITY = [
    "human",        # más crítico
    "doubt",
    "negative",
    "affirmative",
    "later",
]

INTENT_KEYWORDS = {
    "affirmative": ["sí", "si", "ok", "vale", "adelante", "correcto"],
    "negative": ["no", "nop", "incorrecto"],
    "later": ["luego", "después", "más tarde"],
    "doubt": ["duda", "dudas", "no entiendo", "no entiendo bien"],
    "human": ["llamar", "asesor", "persona", "hablar"],
}
def detect_intent(text: str, state) -> str:
    text = text.lower()

    detected = set()

    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            detected.add(intent)

    # 🔥 Si no detectó nada
    if not detected:
        return "other"

    # 🔥 Si solo hay uno
    if len(detected) == 1:
        return detected.pop()

    # 🔥 Prioridad global
    for intent in INTENT_PRIORITY:
        if intent in detected:
            return intent

    return "other"
