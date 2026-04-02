from sqlalchemy.orm import Session
from app.db.models import Message


def save_message(
    db: Session,
    session_id: int,
    phone: str,
    direction: str,
    content: str | None = None,
    message_id: str | None = None,
    type: str = "text",
    media_url: str | None = None,
    file_name: str | None = None
):

    msg = Message(
        session_id=session_id,
        phone=phone,
        direction=direction,
        content=content,
        message_id=message_id,
        type=type,
        media_url=media_url,
        file_name=file_name
    )

    db.add(msg)

    return msg