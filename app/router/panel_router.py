from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc
from datetime import datetime

from app.schemas.panel import (
    SendMessageRequest,
    ConversationResponse,
    MessageResponse,
    PaginatedMessagesResponse
)

from app.adapters.whatsapp_client import send_whatsapp_message
from app.db.session import get_db
from app.db.models import ChatSessions, Message

# from app.core.security import verify_api_key  # opcional

router = APIRouter(
    prefix="/api/panel",
    tags=["panel"]
)


# =========================================
# Obtener conversaciones (PAGINADO + DTO)
# =========================================
@router.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    # _: str = Depends(verify_api_key)
):
    if limit > 100:
        limit = 100

    sessions = (
        db.query(ChatSessions)
        .order_by(desc(ChatSessions.last_message_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        ConversationResponse(
            id=s.id,
            phone=s.phone,
            last_message_at=s.last_message_at
        )
        for s in sessions
    ]


# =========================================
# Obtener mensajes (PAGINADO REAL)
# =========================================
@router.get("/messages/{session_id}", response_model=PaginatedMessagesResponse)
def get_messages(
    session_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    # _: str = Depends(verify_api_key)
):
    if limit > 200:
        limit = 200

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not session:
        raise HTTPException(404, "La sesión no existe")

    base_query = db.query(Message).filter(
        Message.session_id == session_id
    )

    total = base_query.count()

    messages = (
        base_query
        .order_by(asc(Message.created_at), asc(Message.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return PaginatedMessagesResponse(
        data=[
            MessageResponse(
                id=m.id,
                direction=m.direction,
                content=m.content,
                created_at=m.created_at
            )
            for m in messages
        ],
        total=total,
        has_more=(offset + limit) < total
    )


# =========================================
# Enviar mensaje desde panel (SEGURO + CONSISTENTE)
# =========================================
@router.post("/messages")
def send_agent_message(
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    # _: str = Depends(verify_api_key)
):
    # VALIDACIONES
    content = payload.content.strip()

    if not content:
        raise HTTPException(400, "Mensaje vacío")

    if len(content) > 1000:
        raise HTTPException(400, "Mensaje demasiado largo")

    # SESSION
    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == payload.session_id)
        .first()
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    phone = session.phone  # ⚠️ NO confiar en frontend

    try:
        # ENVÍO EXTERNO
        send_whatsapp_message(phone, content)

        # PERSISTENCIA
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content
        )

        db.add(message)

        # ACTUALIZAR ORDEN DE CONVERSACIONES
        session.last_message_at = datetime.utcnow()

        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error enviando mensaje a WhatsApp"
        )

    return {"status": "sent"}