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
    return session


def update_session(session_id: int, state: ChatState, last_message: str | None):
    db = SessionLocal()

    session = db.query(ChatSession).get(session_id)
    session.state = state.value
    session.last_message = last_message

    db.commit()
    db.close()
