import re

FOLIO_REGEX = re.compile(r"(folio|numero de folio)\s*[:\-]?\s*(\w+)", re.IGNORECASE)


def extract_folio(text: str) -> str | None:
    if not text:
        return None

    match = FOLIO_REGEX.search(text)
    if match:
        return match.group(2)

    return None

def extraer_folio(texto: str) -> str | None:
    """
    Extrae un posible folio del texto enviado por el usuario.
    Busca cualquier número de 4 a 7 dígitos dentro del mensaje.
    """

    if not texto:
        return None

    match = re.search(r"\b\d{4,7}\b", texto)

    if match:
        return match.group()

    return None