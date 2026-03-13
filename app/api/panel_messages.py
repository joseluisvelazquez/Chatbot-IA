from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Message

router = APIRouter(prefix="/api", tags=["panel"])


@router.get("/messages/{session_id}")
def get_messages(session_id: int, db: Session = Depends(get_db)):

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    result = []

    for m in messages:
        result.append({
            "direction": m.direction,
            "content": m.content,
            "created_at": m.created_at
        })

    return result