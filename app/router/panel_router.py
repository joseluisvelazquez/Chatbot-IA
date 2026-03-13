from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import ChatSession

router = APIRouter(prefix="/api/panel", tags=["panel"])


@router.get("/conversations")
def get_conversations(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):

    sessions = (
        db.query(ChatSession)
        .order_by(ChatSession.last_message_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return sessions