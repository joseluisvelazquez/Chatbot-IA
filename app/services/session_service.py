from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db.models import ChatSessions
from app.core.states import ChatState


def get_or_create_session(db: Session, phone: str, folio: str | None = None):
    """
    Obtiene la sesión bloqueando la fila.
    Si no existe la crea de forma segura contra concurrencia.
    """

    # 1️⃣ intentar obtener con lock
    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.phone == phone)
        .with_for_update(nowait=True)
        .first()
    )

    if session:
        return session

    # 2️⃣ crear sesión (puede competir con otro request)
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
        # otro proceso la creó primero
        db.rollback()

        # volver a leer con lock
        session = (
            db.query(ChatSessions)
            .filter(ChatSessions.phone == phone)
            .with_for_update()
            .first()
        )

        return session
    
def update_session(
    session: ChatSessions,
    state: str,
    last_message: str,
    previous_state: str | None = None,
    message_id: str | None = None,
):
    """
    Solo muta el objeto dentro de la transacción.
    El commit lo controla el webhook.
    """

    session.state = state
    session.last_message = last_message

    if previous_state is not None:
        session.previous_state = previous_state

    # anti duplicado
    if message_id:
        session.last_message_id = message_id

    return session
