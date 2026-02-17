from sqlalchemy.orm import Session
from app.db.models import ChatSession
from app.core.states import ChatState


def get_or_create_session(db: Session, phone: str, folio: str | None = None):
    session = db.query(ChatSession).filter_by(phone=phone).first()

    if not session:
        session = ChatSession(
            phone=phone,
            folio=folio,
            state=ChatState.ESPERA.value,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    return session  # 👈 objeto vivo ligado a la sesión


def update_session(
    db: Session,
    session: ChatSession,
    state: str,
    last_message: str,
    previous_state: str | None = None,
    message_id: str | None = None,
):
    session.state = state
    session.last_message = last_message

    if previous_state is not None:
        session.previous_state = previous_state

    if message_id is not None:
        session.last_message_id = message_id

    db.commit()
    db.refresh(session)

    return session
