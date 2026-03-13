from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import ChatSessions

router = APIRouter(prefix="/api", tags=["panel"])


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db)):

    sessions = (
        db.query(ChatSessions)
        .order_by(ChatSessions.last_message_at.desc())
        .limit(50)
        .all()
    )

    result = []

    for s in sessions:
        result.append({
            "session_id": s.id,
            "phone": s.phone,
            "state": s.state,
            "folio": s.folio,
            "last_message": s.last_message,
            "last_message_at": s.last_message_at
        })

    return result