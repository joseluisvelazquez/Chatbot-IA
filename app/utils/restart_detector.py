RESTART_KEYWORDS = [
    "reiniciar",
    "empezar",
    "volver a empezar",
    "iniciar verificacion",
    "iniciar verificación",
    "comenzar",
    "reset",
    "otra vez",
]


def wants_restart(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    return any(k in text for k in RESTART_KEYWORDS)
