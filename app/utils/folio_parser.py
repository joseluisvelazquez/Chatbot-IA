import re

FOLIO_REGEX = re.compile(r"(folio|numero de folio)\s*[:\-]?\s*(\w+)", re.IGNORECASE)


def extract_folio(text: str) -> str | None:
    if not text:
        return None

    match = FOLIO_REGEX.search(text)
    if match:
        return match.group(2)

    return None
