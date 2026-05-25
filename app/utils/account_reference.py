from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


MISSING_REFERENCE_VALUES = {"-", "null", "none", "undefined", "no disponible"}
ACCOUNT_KEYS = {
    "account",
    "account_number",
    "account_reference",
    "cuenta",
    "cuenta_formateada",
    "no_cuenta",
    "numero_cuenta",
    "numero_cuenta_formateada",
    "numero_cuenta_referencia",
    "payment_account_reference",
}
PREFIX_KEYS = {
    "account_prefix",
    "prefijo",
    "prefijo_cuenta",
}
PREFIX_REQUIRED_KEYS = {
    "account_prefix_required",
    "requires_account_prefix",
    "requiere_prefijo_cuenta",
}


@dataclass(slots=True)
class AccountReferenceResolution:
    raw: str | None
    formatted: str | None
    prefix: str | None
    source: str | None
    valid: bool
    reason: str | None = None
    conflict: bool = False
    conflict_reason: str | None = None


def clean_account_reference_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in MISSING_REFERENCE_VALUES:
        return None
    return text


def format_account_reference(numero_cuenta: Any) -> str | None:
    text = clean_account_reference_value(numero_cuenta)
    if not text:
        return None
    first = text[:1].upper()
    if first in {"A", "B"} and len(text) > 1:
        return first + text[1:].strip()
    if text[:1].isalpha():
        return text
    return f"A{text}"


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "si", "s", "yes", "y"}


def _account_prefix(value: Any) -> str | None:
    text = clean_account_reference_value(value)
    if not text or not text[:1].isalpha() or len(text) <= 1:
        return None
    return text[:1].upper()


def _explicit_prefix(value: Any) -> str | None:
    text = clean_account_reference_value(value)
    if not text:
        return None
    text = text.upper()
    return text if re.fullmatch(r"[A-Z]", text) else None


def _object_value(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _collect_mapping_candidates(
    value: Any,
    *,
    source: str,
    candidates: list[tuple[str, str]],
    prefixes: list[tuple[str, str]],
    required: list[tuple[str, Any]],
) -> None:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            path = f"{source}.{key_text}" if source else key_text

            if key_lower in PREFIX_REQUIRED_KEYS:
                required.append((path, inner))
            if key_lower in PREFIX_KEYS:
                prefix = _explicit_prefix(inner)
                if prefix:
                    prefixes.append((prefix, path))
                elif clean_account_reference_value(inner):
                    prefixes.append((str(inner), path))

            if key_lower in ACCOUNT_KEYS:
                if isinstance(inner, Mapping):
                    _collect_mapping_candidates(
                        inner,
                        source=path,
                        candidates=candidates,
                        prefixes=prefixes,
                        required=required,
                    )
                else:
                    text = clean_account_reference_value(inner)
                    if text:
                        candidates.append((text, path))

            if isinstance(inner, Mapping):
                _collect_mapping_candidates(
                    inner,
                    source=path,
                    candidates=candidates,
                    prefixes=prefixes,
                    required=required,
                )
            elif isinstance(inner, list):
                for index, item in enumerate(inner):
                    if isinstance(item, Mapping):
                        _collect_mapping_candidates(
                            item,
                            source=f"{path}[{index}]",
                            candidates=candidates,
                            prefixes=prefixes,
                            required=required,
                        )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                _collect_mapping_candidates(
                    item,
                    source=f"{source}[{index}]",
                    candidates=candidates,
                    prefixes=prefixes,
                    required=required,
                )


def resolve_payment_account_reference(
    *records: Any,
    raw_account: Any = None,
    venta: Any = None,
    snapshot: Any = None,
    bridge_sale: Any = None,
) -> AccountReferenceResolution:
    candidates: list[tuple[str, str]] = []
    prefixes: list[tuple[str, str]] = []
    required: list[tuple[str, Any]] = []

    raw_text = clean_account_reference_value(raw_account)
    if raw_text:
        candidates.append((raw_text, "raw_account"))

    for label, obj in (
        ("venta", venta),
        ("snapshot", snapshot),
        ("bridge_sale", bridge_sale),
    ):
        if not obj:
            continue
        for key in ("no_cuenta", "numero_cuenta", "cuenta", "account_number"):
            text = clean_account_reference_value(_object_value(obj, key))
            if text:
                candidates.append((text, f"{label}.{key}"))
        if isinstance(obj, Mapping):
            _collect_mapping_candidates(
                obj,
                source=label,
                candidates=candidates,
                prefixes=prefixes,
                required=required,
            )

    for index, record in enumerate(records):
        _collect_mapping_candidates(
            record,
            source=f"record[{index}]",
            candidates=candidates,
            prefixes=prefixes,
            required=required,
        )

    raw_candidate = candidates[0] if candidates else (None, None)
    raw_value, raw_source = raw_candidate

    for value, source in candidates:
        prefix = _account_prefix(value)
        if prefix:
            formatted = format_account_reference(value)
            return AccountReferenceResolution(
                raw=raw_value,
                formatted=formatted,
                prefix=prefix,
                source=source,
                valid=True,
                conflict=bool(raw_value and formatted and raw_value != formatted and source != raw_source),
                conflict_reason=(
                    "raw_account_differs_from_prefixed_candidate"
                    if raw_value and formatted and raw_value != formatted and source != raw_source
                    else None
                ),
            )

    explicit_prefix = next(((prefix, source) for prefix, source in prefixes if prefix in {"A", "B"}), None)
    invalid_prefix = next((prefix for prefix, _source in prefixes if prefix and prefix not in {"A", "B"}), None)
    if invalid_prefix:
        return AccountReferenceResolution(
            raw=raw_value,
            formatted=None,
            prefix=None,
            source=None,
            valid=False,
            reason="unsupported_account_prefix",
        )
    if explicit_prefix:
        prefix, source = explicit_prefix
        if not raw_value:
            return AccountReferenceResolution(
                raw=None,
                formatted=None,
                prefix=prefix,
                source=source,
                valid=False,
                reason="missing_account_number_for_prefix",
            )
        return AccountReferenceResolution(
            raw=raw_value,
            formatted=f"{prefix}{raw_value}",
            prefix=prefix,
            source=source,
            valid=True,
        )

    if any(_is_truthy(value) for _source, value in required):
        return AccountReferenceResolution(
            raw=raw_value,
            formatted=None,
            prefix=None,
            source=None,
            valid=False,
            reason="account_prefix_required_but_missing",
        )

    formatted = format_account_reference(raw_value)
    return AccountReferenceResolution(
        raw=raw_value,
        formatted=formatted,
        prefix=_account_prefix(formatted),
        source="info_comprobante_acceso_default" if formatted else raw_source,
        valid=bool(formatted),
        reason=None if formatted else "missing_account_reference",
    )
