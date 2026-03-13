from __future__ import annotations

from typing import Any, Dict

# Progreso de verificación (0/1) por paso.
# Mantén esto como contrato estable del JSON guardado en DB.
DEFAULT_VERIFICATION_PROGRESS: Dict[str, int] = {
    "inicio": 0,
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
}


def assert_valid_step(step: str) -> None:
    if step not in DEFAULT_VERIFICATION_PROGRESS:
        raise ValueError(f"Paso de verificación desconocido: {step}")


def normalize_progress_payload(payload):
    if not isinstance(payload, dict):
        payload = {}

    data = payload.copy()

    for k in DEFAULT_VERIFICATION_PROGRESS.keys():
        if k not in data:
            data[k] = 0

    return data
