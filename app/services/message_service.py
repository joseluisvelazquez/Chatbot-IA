from sqlalchemy.orm import Session
from app.db.models import Message
from app.utils.timezone import mexico_now_naive


def save_message(
    db: Session,
    session_id: int,
    phone: str,
    direction: str,
    content: str | None = None,
    message_id: str | None = None,
    type: str = "text",
    media_url: str | None = None,
    file_name: str | None = None,
    created_at = None,
    extra_json: dict | None = None,
):

    values = {
        "session_id": session_id,
        "phone": phone,
        "direction": direction,
        "content": content,
        "message_id": message_id,
        "type": type,
        "media_url": media_url,
        "file_name": file_name,
        "extra_json": extra_json,
    }

    values["created_at"] = created_at or mexico_now_naive()

    msg = Message(**values)

    db.add(msg)

    return msg


def get_message_by_message_id(db: Session, message_id: str | None) -> Message | None:
    if not message_id:
        return None

    return db.query(Message).filter(Message.message_id == message_id).first()
