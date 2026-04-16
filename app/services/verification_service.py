from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.verification.verification_schema import (
    DEFAULT_VERIFICATION_PROGRESS,
    VERIFICATION_STEP_ORDER,
    assert_valid_step,
    normalize_progress_payload,
)
from app.db.models import FlowEvent, VerificacionCuenta
from app.siga.siga_repository import obtener_venta_por_folio

logger = logging.getLogger(__name__)


class VerificationTransitionError(ValueError):
    """La transicion solicitada no respeta el contrato de verificacion."""


@dataclass(frozen=True)
class VerificationResult:
    no_cuenta: str
    progress: Dict[str, int]
    version: int
    changed: bool


def log_flow_event(
    db: Session,
    session,
    from_state: str | None,
    to_state: str | None,
    trigger_text: str | None,
    event_type: str,
    detected_intent: str | None = None,
    event_payload: dict | None = None,
):
    try:
        event = FlowEvent(
            session_id=session.id,
            phone=session.phone,
            folio=session.folio,
            from_state=from_state,
            to_state=to_state,
            trigger_text=trigger_text,
            event_type=event_type,
            detected_intent=detected_intent,
            event_payload=event_payload,
        )

        db.add(event)
        db.flush()

    except Exception:
        logger.exception(
            "flow_event_log_failed",
            extra={
                "session_id": getattr(session, "id", None),
                "phone": getattr(session, "phone", None),
                "from_state": from_state,
                "to_state": to_state,
                "event_type": event_type,
            },
        )


def is_verification_complete(payload: Dict[str, Any]) -> bool:
    data = normalize_progress_payload(payload)
    return data["finalizado"] == 1


class VerificationService:
    """Store persistente de avance por no_cuenta.

    Invariantes:
    - una fila por no_cuenta;
    - pasos secuenciales segun VERIFICATION_STEP_ORDER;
    - actualizaciones idempotentes;
    - sin regresiones salvo override explicito;
    - version incrementada solo cuando cambia el JSON.
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
            version=0,
        )

        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            logger.info(
                "verification_store_create_race",
                extra={"no_cuenta": no_cuenta},
            )

    def _lock_row(self, no_cuenta: str) -> VerificacionCuenta:
        row = (
            self.db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .with_for_update()
            .first()
        )

        if row:
            return row

        self._create_if_missing(no_cuenta)

        row = (
            self.db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .with_for_update()
            .first()
        )

        if not row:
            raise RuntimeError("No se pudo crear o bloquear VerificacionCuenta")

        return row

    def _validate_transition(
        self,
        progress: Dict[str, int],
        step: str,
        value: int,
        *,
        allow_override: bool,
    ) -> None:
        index = VERIFICATION_STEP_ORDER.index(step)
        previous_steps = VERIFICATION_STEP_ORDER[:index]
        previous_incomplete = [item for item in previous_steps if progress.get(item, 0) == 0]

        if previous_incomplete:
            raise VerificationTransitionError(
                f"No se puede marcar {step}; pasos previos incompletos: {', '.join(previous_incomplete)}"
            )

        if step == "finalizado":
            incomplete = [
                item
                for item in VERIFICATION_STEP_ORDER
                if item != "finalizado" and progress.get(item, 0) == 0
            ]
            if incomplete:
                raise VerificationTransitionError(
                    f"No se puede finalizar; pasos incompletos: {', '.join(incomplete)}"
                )

        if progress.get("finalizado") and step != "finalizado" and not allow_override:
            raise VerificationTransitionError(
                "La verificacion ya esta finalizada; requiere override explicito"
            )

        current_value = progress.get(step, 0)
        if current_value != 0 and current_value != value and not allow_override:
            raise VerificationTransitionError(
                f"No se permite sobrescribir {step} de {current_value} a {value} sin override"
            )

        if value == 0 and current_value != 0 and not allow_override:
            raise VerificationTransitionError(
                f"No se permite regresar {step} a 0 sin override"
            )

    def update_step_atomic(
        self,
        no_cuenta: str,
        step: str,
        value: int = 1,
        phone: str | None = None,
        *,
        allow_override: bool = False,
        event_id: str | None = None,
    ) -> VerificationResult:
        if not no_cuenta:
            raise ValueError("no_cuenta requerido")

        if not step:
            raise ValueError("step requerido")

        if value not in (0, 1, 2, 3):
            raise ValueError("valor invalido de verificacion")

        assert_valid_step(step)

        row = self._lock_row(no_cuenta)
        progress = normalize_progress_payload(row.json)
        current_version = int(getattr(row, "version", 0) or 0)
        current_value = progress.get(step, 0)

        if current_value == value:
            logger.info(
                "verification_transition_idempotent",
                extra={
                    "no_cuenta": no_cuenta,
                    "step": step,
                    "value": value,
                    "version": current_version,
                    "event_id": event_id,
                },
            )
            return VerificationResult(
                no_cuenta=no_cuenta,
                progress=progress,
                version=current_version,
                changed=False,
            )

        self._validate_transition(
            progress,
            step,
            value,
            allow_override=allow_override,
        )

        next_progress = progress.copy()
        next_progress[step] = value

        row.json = next_progress
        row.version = current_version + 1

        try:
            self.db.flush()
        except Exception:
            logger.exception(
                "verification_transition_persist_failed",
                extra={
                    "no_cuenta": no_cuenta,
                    "step": step,
                    "value": value,
                    "phone": phone,
                    "event_id": event_id,
                },
            )
            raise

        logger.info(
            "verification_transition_persisted",
            extra={
                "no_cuenta": no_cuenta,
                "step": step,
                "from_value": current_value,
                "to_value": value,
                "version": row.version,
                "phone": phone,
                "event_id": event_id,
            },
        )

        return VerificationResult(
            no_cuenta=no_cuenta,
            progress=next_progress,
            version=row.version,
            changed=True,
        )

    def mark_step_from_folio(
        self,
        folio: str,
        step: str,
        value: int,
        phone: str,
        *,
        allow_override: bool = False,
        event_id: str | None = None,
    ) -> Optional[VerificationResult]:
        no_cuenta = self.resolve_no_cuenta_from_folio(folio)
        if not no_cuenta:
            return None

        return self.update_step_atomic(
            no_cuenta=no_cuenta,
            step=step,
            value=value,
            phone=phone,
            allow_override=allow_override,
            event_id=event_id,
        )
