import re
import unicodedata

FOLIO_REGEX = re.compile(
    r"(?:numero\s+de\s+folio|folio)\s*(?:es)?\s*[:#\-]?\s*([a-z0-9][a-z0-9\-]*)",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    text = str(text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def extraer_folio_explicito(texto: str) -> str | None:
    """
    Extrae folios cuando el usuario los identifica como folio.

    A diferencia de ``extraer_folio``, no toma cualquier numero largo del texto.
    Esto evita confundir montos, telefonos o codigos con folios durante el flujo.
    """

    if not texto:
        return None

    match = FOLIO_REGEX.search(_normalize_text(texto))
    if not match:
        return None

    folio = (match.group(1) or "").strip()
    if not re.search(r"\d", folio):
        return None
    return folio or None


def extract_folio(text: str) -> str | None:
    if not text:
        return None

    return extraer_folio_explicito(text)

def extraer_folio(texto: str) -> str | None:
    """
    Extrae un posible folio del texto enviado por el usuario.
    Busca cualquier número de 4 a 7 dígitos dentro del mensaje.
    """

    if not texto:
        return None

    match = re.search(r"\b\d{4,12}\b", texto)

    if match:
        return match.group()

    return None


def es_folio_suelto(texto: str, folio: str | None = None) -> bool:
    """
    True si el mensaje completo es basicamente el folio.

    Se usa solo en estados donde el bot ya esta esperando un folio; en el resto
    del flujo se exige una mencion explicita como "mi folio es 12345".
    """

    candidate = str(folio or extraer_folio(texto) or "").strip()
    if not texto or not candidate:
        return False

    tokens = re.findall(r"[a-z0-9]+", _normalize_text(texto))
    candidate_norm = _normalize_text(candidate)
    return tokens == [candidate_norm]


def extraer_folio_si_mensaje_de_folio(
    texto: str,
    *,
    allow_folio_suelto: bool = False,
) -> str | None:
    explicit = extraer_folio_explicito(texto)
    if explicit:
        return explicit

    candidate = extraer_folio(texto)
    if allow_folio_suelto and es_folio_suelto(texto, candidate):
        return candidate

    return None
