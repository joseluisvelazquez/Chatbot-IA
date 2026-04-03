from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import ChatSessions
from app.adapters.whatsapp_client import send_whatsapp_message
from app.services.message_service import save_message
from app.security.auth_dependencies import get_current_panel_user, require_roles
from app.websockets import manager

#Para enviar mensajes desde el panel de administración a WhatsApp

from pydantic import BaseModel
from app.adapters.whatsapp_client import send_whatsapp_media
from app.db.models import Message
from datetime import datetime

router = APIRouter(prefix="/api/panel", tags=["panel"])
class SendFileRequest(BaseModel):
    session_id: int
    media_url: str
    file_name: str | None = None
    type: str  # image | document

@router.post("/send")
async def send_message(
    session_id: int,
    message: str,
    db: Session = Depends(get_db),
    user = Depends(require_roles("ventas", "admin", "cobranza")),
):

    chat = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

    if not chat:
        return {"error": "session not found"}
    # 🔥 VALIDACIÓN EMPRESA (mínimo control multi-tenant)
    if user.empresa_id != 1:
        raise HTTPException(status_code=403, detail="Acceso no permitido")

    # enviar a WhatsApp
    await send_whatsapp_message(chat.phone, message)
    

    # guardar mensaje
    save_message(
        db=db,
        session_id=session_id,
        phone=chat.phone,
        direction="agent",
        content=message
    )
    
    db.commit()
    

    return {"status": "sent"}
# Endpoint para enviar archivos (imágenes, documentos) desde el panel a WhatsApp
@router.post("/messages/file")
async def send_file_message(
    payload: SendFileRequest,
    db: Session = Depends(get_db)
):
    chat = db.query(ChatSessions).filter(
        ChatSessions.id == payload.session_id
    ).first()

    if not chat:
        raise HTTPException(status_code=404, detail="Session not found")

    phone = chat.phone

    # -----------------------
    # 💾 GUARDAR EN DB
    # -----------------------
    msg = Message(
        session_id=chat.id,
        phone=phone,
        direction="agent",
        content="[MEDIA]",
        type=payload.type,
        media_url=payload.media_url,
        file_name=payload.file_name
    )

    db.add(msg)

    chat.last_message = "[MEDIA]"
    chat.last_message_at = datetime.utcnow()
    chat.unread_count = 0

    db.commit()
    # -----------------------
    # 📡 WEBSOCKET
    # -----------------------
    from app.websockets.manager import manager

    await manager.send_to_all({
        "type": "new_message",
        "session_id": chat.id,
        "message": {
            "id": msg.id,
            "content": None,
            "direction": "agent",
            "type": payload.type,
            "media_url": payload.media_url,
            "file_name": payload.file_name
        },
        "unread_count": chat.unread_count
    })

    # -----------------------
    # 📤 WHATSAPP
    # -----------------------
    try:
        await send_whatsapp_media(
            phone=phone,
            media_url=payload.media_url,
            media_type=payload.type,
            filename=payload.file_name
        )
    except Exception as e:
        print(f"[WHATSAPP ERROR] phone={phone} error={e}")

    return {"status": "sent"}