from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas.panel import SendMessageRequest
from app.adapters.whatsapp_client import send_whatsapp_message
from app.db.session import get_db
from app.db.models import ChatSessions, Message

router = APIRouter(prefix="/api/panel", tags=["panel"])


# =========================================
# Obtener conversaciones
# =========================================
@router.get("/conversations")
def get_conversations(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):

    sessions = (
        db.query(ChatSessions)
        .order_by(ChatSessions.last_message_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return sessions


# =========================================
# Obtener mensajes de conversación
# =========================================
@router.get("/messages/{session_id}")
def get_messages(
    session_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="La sesión no existe"
        )

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "direction": m.direction,
            "content": m.content,
            "created_at": m.created_at
        }
        for m in messages
    ]


# =========================================
# Enviar mensaje desde panel
# =========================================
@router.post("/messages")
def send_agent_message(
    payload: SendMessageRequest,
    db: Session = Depends(get_db)
):

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == payload.session_id)
        .first()
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Sesión no encontrada"
        )

    # enviar mensaje a WhatsApp
    send_whatsapp_message(payload.phone, payload.content)

    # guardar mensaje
    message = Message(
        session_id=payload.session_id,
        phone=payload.phone,
        direction="agent",
        content=payload.content
    )

    db.add(message)
    db.commit()

    return {"status": "sent"}