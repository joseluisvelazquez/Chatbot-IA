from sqlalchemy.orm import Session
from app.db.models import Message


def save_message(
    db: Session,
    session_id: int,
    phone: str,
    direction: str,
    content: str,
    message_id: str | None = None
):

    msg = Message(
        session_id=session_id,
        phone=phone,
        direction=direction,
        content=content,
        message_id=message_id
    )

    db.add(msg)

    return msg