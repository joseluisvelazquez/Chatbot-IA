from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.models import ChatSessions
from app.core.states import ChatState


def utcnow_naive() -> datetime:
    """
    MySQL DATETIME no almacena TZ; guardamos naive UTC consistentemente.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_or_create_session(db: Session, phone: str, folio: str | None = None) -> ChatSessions:
    """
    Obtiene la sesión intentando lock de fila.
    Si no existe, la crea de forma segura contra concurrencia.

    Nota: with_for_update(nowait=True) puede lanzar OperationalError si la fila está bloqueada.
    En ese caso, hacemos fallback a lectura sin nowait (bloqueante) o sin lock.
    """

    if not phone:
        raise ValueError("phone is required")

    # 1) Intentar obtener con lock NOWAIT (rápido; puede fallar por lock contention)
    try:
        session = (
            db.query(ChatSessions)
            .filter(ChatSessions.phone == phone)
            .with_for_update(nowait=True)
            .first()
        )
        if session:
            return session

    except OperationalError:
        # Otro request tiene el lock; fallback a lectura normal para no romper el flujo.
        db.rollback()
        session = db.query(ChatSessions).filter(ChatSessions.phone == phone).first()
        if session:
            return session
        # si no existe, continuamos a crear

    # 2) Crear sesión (puede competir con otro request)
    session = ChatSessions(
        phone=phone,
        folio=folio,
        state=ChatState.ESPERA.value,
    )
    db.add(session)

    try:
        db.flush()  # intenta insertar
        return session

    except IntegrityError:
        # Otro proceso la creó primero
        db.rollback()

        # Volver a leer (idealmente con lock pero sin nowait para evitar crash)
        try:
            session = (
                db.query(ChatSessions)
                .filter(ChatSessions.phone == phone)
                .with_for_update()
                .first()
            )
        except OperationalError:
            db.rollback()
            session = db.query(ChatSessions).filter(ChatSessions.phone == phone).first()

        if not session:
            # Esto sería raro (integrity error pero no aparece)
            raise

        return session


def update_session(
    session: ChatSessions,
    state: str,
    last_message: Optional[str],
    previous_state: str | None = None,
    message_id: str | None = None,
    *,
    last_message_at: Optional[datetime] = None,
) -> ChatSessions:
    """
    Solo muta el objeto dentro de la transacción.
    El commit lo controla el webhook.

    Cambios clave:
    - Guarda last_message_at (fuente de verdad para recordatorios).
    - Mantiene updated_at alineado con last_message_at.
    - Permite last_message None (ej: interacción por botón sin texto).
    """

    if session is None:
        raise ValueError("session is required")
    if not state:
        raise ValueError("state is required")

    session.state = state

    # last_message puede ser None si el input fue solo botón
    if last_message is not None:
        session.last_message = last_message

    if previous_state is not None:
        session.previous_state = previous_state

    # Anti duplicado (el webhook debería checarlo antes, pero aquí lo persistimos)
    if message_id:
        session.last_message_id = message_id

    # ✅ CLAVE: timestamp de último mensaje para inactividad
    ts = last_message_at or utcnow_naive()
    session.last_message_at = ts
    session.updated_at = ts

    return session