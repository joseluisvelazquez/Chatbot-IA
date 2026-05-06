from __future__ import annotations

from typing import Any, Dict

DEFAULT_VERIFICATION_PROGRESS: Dict[str, int] = {
    "folio": 0,
    "nombre": 0,
    "domicilio": 0,
    "fecha": 0,
    "producto": 0,
    "componentes": 0,
    "pagoInicial": 0,
    "pagos": 0,
    "bancos": 0,
    "plan3meses": 0,
    "planes": 0,
    "beneficios": 0,
    "finalizado": 0,
}

VERIFICATION_STEP_ORDER = list(DEFAULT_VERIFICATION_PROGRESS.keys())
NON_TRACKABLE_VERIFICATION_STEPS = {"inicio"}


def assert_valid_step(step: str) -> None:
    if step not in DEFAULT_VERIFICATION_PROGRESS:
        raise ValueError(f"Paso de verificacion desconocido: {step}")


def is_trackable_step(step: str | None) -> bool:
    return bool(step) and step in DEFAULT_VERIFICATION_PROGRESS


def is_non_trackable_step(step: str | None) -> bool:
    return bool(step) and step in NON_TRACKABLE_VERIFICATION_STEPS


def normalize_progress_payload(payload: Dict[str, Any] | None) -> Dict[str, int]:
    if not isinstance(payload, dict):
        payload = {}

    data: Dict[str, int] = {}

    for key in VERIFICATION_STEP_ORDER:
        raw_value = payload.get(key, 0)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 0

        data[key] = value if value in (0, 1, 2, 3) else 0

    return data
