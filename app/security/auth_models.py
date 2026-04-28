from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PanelRole = Literal["admin", "ventas", "cobranza", "sistemas", "jefe_operativo", "viewer"]


@dataclass(frozen=True)
class PanelUser:
    username: str
    puesto: str
    empresa_id: int
    role: PanelRole
    exp: int
    jti: str | None = None
