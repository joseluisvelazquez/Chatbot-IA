from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.models import ChatSessions
from app.core.states.states import ChatState
from app.utils.folio_parser import extraer_folio_si_mensaje_de_folio
from app.utils.timezone import mexico_now_naive

def attach_folio_to_session(db, session, folio):
    
    # ya existe una sesión con ese folio?
    existing = db.query(ChatSessions).filter(
        ChatSessions.phone == session.phone,
        ChatSessions.folio == folio
    ).first()

    if existing:
        return existing

    #  crear nueva sesión con folio
    new_session = ChatSessions(
        phone=session.phone,
        folio=folio,
        state=session.state,
        last_message=session.last_message,
        last_message_at=session.last_message_at,
        last_customer_message_at=session.last_message_at or utcnow_naive(),
    )

    db.add(new_session)
    db.flush()

    return new_session

def utcnow_naive() -> datetime:
    """
    MySQL DATETIME no almacena TZ; guardamos hora local de Mexico.
    """
    return mexico_now_naive()


def get_or_create_session(db: Session, phone: str, folio: str | None = None, text: str = "", intent: str = "") -> ChatSessions:
    """
    Obtiene la sesión más reciente intentando lock de fila.
    Si la última sesión está en un estado terminal, SOLO crea una nueva sesión 
    si el usuario tiene la intención explícita de iniciar una nueva verificación.
    """
    if not phone:
        raise ValueError("phone is required")

    terminal_states = [
        ChatState.FINALIZADO.value, 
        ChatState.DEVOLUCION_FINALIZADA.value,
        ChatState.FUERA_DE_FLUJO.value,
        ChatState.LLAMADA.value,
        ChatState.ACLARACION.value
    ]

    # 1) Intentar obtener la sesión más reciente
    try:
        session = (
            db.query(ChatSessions)
            .filter(ChatSessions.phone == phone)
            .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
            .with_for_update(nowait=True)
            .first()
        )
    except OperationalError:
        # Otro request tiene el lock; fallback a lectura normal
        db.rollback()
        session = (
            db.query(ChatSessions)
            .filter(ChatSessions.phone == phone)
            .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
            .first()
        )

    is_session_finished = False
    if session:
        if session.state in terminal_states:
            is_session_finished = True

    # Si hay sesión y NO está finalizada, la retornamos
    if session and not is_session_finished:
        return session

    # Si está finalizada, verificamos si quiere iniciar otra verificación
    if session and is_session_finished:
        # Validar si el usuario quiere verificar otro folio
        is_starting_new = False
        if intent in ["MENU_VERIFICACION", "SELECCIONAR_FOLIO"] or (intent and intent.startswith("SELECCIONAR_FOLIO_")):
            is_starting_new = True
        elif text:
            stripped = text.strip()
            folio_val = extraer_folio_si_mensaje_de_folio(
                stripped,
                allow_folio_suelto=True,
            )
            if folio_val:
                is_starting_new = True
            elif stripped.lower() in ["verificar", "verificacion", "otro folio", "nueva verificacion", "iniciar verificacion"]:
                is_starting_new = True

        if not is_starting_new:
            return session

    # 2) Si no hay sesión o la anterior ya finalizó Y quiere iniciar una nueva, creamos una nueva
    new_session = ChatSessions(
        phone=phone,
        folio=folio,
        state=ChatState.ESPERA.value,
        last_customer_message_at=utcnow_naive(),
    )
    db.add(new_session)

    try:
        db.flush()
        return new_session

    except IntegrityError:
        db.rollback()
        # Fallback en caso de colisión (aunque ya no hay unique=True en phone)
        try:
            return (
                db.query(ChatSessions)
                .filter(ChatSessions.phone == phone)
                .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
                .with_for_update()
                .first()
            )
        except OperationalError:
            db.rollback()
            return (
                db.query(ChatSessions)
                .filter(ChatSessions.phone == phone)
                .order_by(ChatSessions.last_message_at.desc(), ChatSessions.id.desc())
                .first()
            )


def update_session(
    session: ChatSessions,
    state: str,
    last_message: Optional[str],
    previous_state: str | None = None,
    message_id: str | None = None,
    *,
    last_message_at: Optional[datetime] = None,
    last_customer_message_at: Optional[datetime] = None,
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

    if last_customer_message_at is not None:
        session.last_customer_message_at = last_customer_message_at

    return session
