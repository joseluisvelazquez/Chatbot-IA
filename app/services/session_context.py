from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

_SIGA_FOLIO_CACHE_KEYS = ("verification_cache", "verification_lookup")


def _as_folio(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_folio(row: Any) -> str | None:
    if not isinstance(row, dict):
        return None

    direct = _as_folio(row.get("folio"))
    if direct:
        return direct

    snapshot = row.get("snapshot") or row.get("data")
    if isinstance(snapshot, dict):
        return _as_folio(snapshot.get("folio"))

    return None


def _clean_siga_bridge_payload(payload: dict[str, Any], next_folio: str | None) -> dict[str, Any]:
    cleaned = copy.deepcopy(payload)

    for key in _SIGA_FOLIO_CACHE_KEYS:
        row = cleaned.get(key)
        if not isinstance(row, dict):
            continue

        cached_folio = _row_folio(row)
        if next_folio is None or (cached_folio and cached_folio != next_folio):
            cleaned.pop(key, None)

    return cleaned


def reset_verification_context_for_folio(session: Any, folio: Any) -> None:
    """Replace the active folio and remove transient data tied to a previous folio."""

    if session is None:
        return

    next_folio = _as_folio(folio)
    current_folio = _as_folio(getattr(session, "folio", None))
    changed = current_folio != next_folio

    if changed:
        extra = getattr(session, "extra_json", None)
        if isinstance(extra, dict):
            next_extra = copy.deepcopy(extra)
            siga_payload = next_extra.get("siga_bridge")
            if isinstance(siga_payload, dict):
                cleaned_siga = _clean_siga_bridge_payload(siga_payload, next_folio)
                if cleaned_siga:
                    next_extra["siga_bridge"] = cleaned_siga
                else:
                    next_extra.pop("siga_bridge", None)

            session.extra_json = next_extra
            try:
                flag_modified(session, "extra_json")
            except Exception:
                pass

    session.folio = next_folio
    if changed:
        session.previous_state = None
    if hasattr(session, "invalid_folio_attempts"):
        session.invalid_folio_attempts = 0
    if changed and hasattr(session, "componente_en_verificacion"):
        session.componente_en_verificacion = None
