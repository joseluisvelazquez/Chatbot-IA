from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PanelRole = Literal[
    "admin",
    "jefe_operativo",
    "gestor_cobranza",
    "soporte_tecnico",
    "lectura",
]


@dataclass(frozen=True)
class PanelUser:
    username: str
    puesto: str
    empresa_id: int
    role: PanelRole
    exp: int
    jti: str | None = None
    user_id: str | None = None
