from __future__ import annotations
from sqlalchemy.exc import IntegrityError
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.panel_send import send_message
from app.core.verification_schema import (
    DEFAULT_VERIFICATION_PROGRESS,
    assert_valid_step,
    normalize_progress_payload,
)
from app.db.models import FlowEvent, VerificacionCuenta
from app.siga.siga_repository import obtener_venta_por_folio


@dataclass(frozen=True)
class VerificationResult:
    no_cuenta: str
    progress: Dict[str, int]

def log_flow_event(db, session, from_state, to_state, trigger, event_type):

    event = FlowEvent(
        session_id=session.id,
        phone=session.phone,
        folio=session.folio,
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        event_type=event_type
    )

    db.add(event)
    db.commit()

def is_verification_complete(payload: Dict[str, Any]) -> bool:
    """
    Determina si la verificación ya fue completada.
    Se considera completa si se llegó al paso 'beneficios'
    o si explícitamente se marcó 'finalizado'.
    """
    print(f"DEBUG: Verificación recibida para check completo: {payload}")

    data = normalize_progress_payload(payload)
    print(f"DEBUG: Verificación normalizada para check completo: {data}")

    return data["finalizado"] == 1

class VerificationService:
    """Persistencia del avance de verificación por CUENTA (no por sesión).

    Requisitos:
    - 1 registro por no_cuenta (UNIQUE en DB)
    - Updates con lock (FOR UPDATE) para evitar carreras
    - JSON consistente (contrato estable)
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve_no_cuenta_from_folio(self, folio: str) -> Optional[str]:
        if not folio or not isinstance(folio, str):
            return None

        venta = obtener_venta_por_folio(self.db, folio)
        if not venta:
            return None

        no_cuenta = getattr(venta, "no_cuenta", None) or getattr(venta, "noCuenta", None)
        if not no_cuenta:
            return None

        return str(no_cuenta)

   
    def _create_if_missing(self, no_cuenta: str) -> None:
        if not no_cuenta:
            raise ValueError("no_cuenta requerido")

        row = VerificacionCuenta(
            no_cuenta=no_cuenta,
            json=DEFAULT_VERIFICATION_PROGRESS.copy(),
        )

        # SAVEPOINT: rollback SOLO de este bloque si choca con UNIQUE
        try:
            with self.db.begin_nested():   # <- crea savepoint
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            # otro request lo creó primero; aquí NO tumbamos la transacción externa
            pass

    def update_step_atomic(self, no_cuenta: str, step: str, value: int = 1, phone: str = None) -> VerificationResult:

        if not no_cuenta:
            raise ValueError("no_cuenta requerido")

        if not step:
            raise ValueError("step requerido")

        if value not in (0, 1, 2, 3):
            raise ValueError("valor inválido de verificación")

        assert_valid_step(step)

        row = (
            self.db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .with_for_update()
            .first()
        )

        if not row:
            self._create_if_missing(no_cuenta)

            row = (
                self.db.query(VerificacionCuenta)
                .filter(VerificacionCuenta.no_cuenta == no_cuenta)
                .with_for_update()
                .first()
            )

            if not row:
                raise RuntimeError("No se pudo crear/lockear VerificacionCuenta")

        progress = normalize_progress_payload(row.json)

        progress[step] = value

        row.json = progress

        self.db.flush()

        return VerificationResult(no_cuenta=no_cuenta, progress=progress)

    def mark_step_from_folio(self, folio: str, step: str, value: int, phone: str) -> Optional[VerificationResult]:
        no_cuenta = self.resolve_no_cuenta_from_folio(folio)
        if not no_cuenta:
            return None
        return self.update_step_atomic(no_cuenta=no_cuenta, step=step, value=value, phone=phone)
