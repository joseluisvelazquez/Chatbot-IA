from app.db.session import SessionLocal
from app.db.models import ChatSession
from app.core.states import ChatState


def get_or_create_session(phone: str, folio: str | None = None):
    db = SessionLocal()

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

    db.close()
    return session  # 👈 OBJETO, no ID


def update_session(session_id, state, last_message, previous_state=None):
    db = SessionLocal()
    session = db.query(ChatSession).get(session_id)

    session.state = state
    session.last_message = last_message

    if previous_state is not None:
        session.previous_state = previous_state

    db.commit()
    db.close()
