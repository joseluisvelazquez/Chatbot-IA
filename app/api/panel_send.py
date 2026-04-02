from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import ChatSessions
from app.adapters.whatsapp_client import send_whatsapp_message
from app.services.message_service import save_message
from app.security.auth_dependencies import get_current_panel_user, require_roles
from app.websockets import manager

router = APIRouter(prefix="/api/panel", tags=["panel"])


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