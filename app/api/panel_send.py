from fastapi import APIRouter, Depends, HTTPException
import logging
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import ChatSessions
from app.adapters.whatsapp_client import _extract_meta_message_id, send_whatsapp_message
from app.services.message_service import save_message
from app.security.auth_dependencies import require_roles
from app.security.auth_service import is_allowed_panel_company, restrict_to_assigned

#Para enviar mensajes desde el panel de administración a WhatsApp

from pydantic import BaseModel
from app.adapters.whatsapp_client import _extract_meta_message_id, send_whatsapp_message, send_whatsapp_media, send_template_message
from app.db.models import Message
from app.utils.timezone import mexico_now_naive
from app.services.ws_events import build_new_message_event
from app.services.message_metadata import build_outgoing_media_metadata
from app.core.states.states import ChatState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/panel", tags=["panel"])

class SendFileRequest(BaseModel):
    session_id: int
    media_url: str
    file_name: str | None = None
    type: str  # image | document
    content: str | None = None

class ReactivateRequest(BaseModel):
    template_key: str

@router.post("/send")
async def send_message(
    session_id: int,
    message: str,
    db: Session = Depends(get_db),
    user = Depends(require_roles("ventas", "admin", "cobranza", "jefe_operativo", "sistemas")),
):

    chat = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not chat:
        return {"error": "session not found"}
    #  VALIDACIÓN EMPRESA (mínimo control multi-tenant)
    if not is_allowed_panel_company(user.empresa_id):
        raise HTTPException(status_code=403, detail="Acceso no permitido")

    # enviar a WhatsApp
    response = await send_whatsapp_message(chat.phone, message)
    provider_message_id = _extract_meta_message_id(response)
    

    # guardar mensaje
    msg = save_message(
        db=db,
        session_id=session_id,
        phone=chat.phone,
        direction="agent",
        content=message,
        message_id=provider_message_id,
    )
    now = mexico_now_naive()
    chat.last_message = message
    chat.last_message_at = now
    chat.unread_count = 0
    
    db.commit()
    db.refresh(msg)
    from app.websockets.manager import manager

    await manager.send_to_all(build_new_message_event(chat, msg))
    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "session_id": chat.id,
        },
    })
    

    return {"status": "sent"}
# Endpoint para enviar archivos (imágenes, documentos) desde el panel a WhatsApp
@router.post("/messages/file")
async def send_file_message(
    payload: SendFileRequest,
    db: Session = Depends(get_db),
    user = Depends(require_roles("ventas", "admin", "cobranza", "jefe_operativo", "sistemas")),
):
    chat = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(ChatSessions.id == payload.session_id)
        .first()
    )

    if not chat:
        raise HTTPException(status_code=404, detail="Session not found")

    if not is_allowed_panel_company(user.empresa_id):
        raise HTTPException(status_code=403, detail="Acceso no permitido")

    phone = chat.phone

    # -----------------------
    # 💾 GUARDAR EN DB
    # -----------------------
    content = payload.content if payload.content and payload.content != "[MEDIA]" else None

    now = mexico_now_naive()
    msg = Message(
        session_id=chat.id,
        phone=phone,
        direction="agent",
        content=content,
        type=payload.type,
        media_url=payload.media_url,
        file_name=payload.file_name,
        extra_json=build_outgoing_media_metadata(
            source=payload.media_url,
            caption=content,
            media_type=payload.type,
        ),
        created_at=now,
    )

    db.add(msg)

    chat.last_message = payload.content if payload.content else "📎 Archivo"
    chat.last_message_at = now
    chat.unread_count = 0

    db.commit()
    # -----------------------
    # 📡 WEBSOCKET
    # -----------------------
    from app.websockets.manager import manager

    await manager.send_to_all(build_new_message_event(chat, msg))

    # -----------------------
    # 📤 WHATSAPP
    # -----------------------
    try:
        caption = payload.content if payload.content and payload.content != "[MEDIA]" else None
        await send_whatsapp_media(
            phone=phone,
            media_url=payload.media_url,
            media_type=payload.type,
            filename=payload.file_name,
            caption=caption
        )
    except Exception as e:
        logger.warning(
            "panel_send_file_whatsapp_failed",
            extra={"session_id": chat.id, "error_type": e.__class__.__name__},
        )

    return {"status": "sent"}

@router.post("/conversations/{session_id}/reactivate")
async def reactivate_conversation(
    session_id: int,
    payload: ReactivateRequest,
    db: Session = Depends(get_db),
    user = Depends(require_roles("ventas", "admin", "cobranza", "jefe_operativo", "sistemas")),
):
    chat = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not chat:
        raise HTTPException(status_code=404, detail="Session not found")

    if not is_allowed_panel_company(user.empresa_id):
        raise HTTPException(status_code=403, detail="Acceso no permitido")

    TEMPLATE_MAP = {
        "inactivity": ("reactivacion_inactividad", "👋🏻 Hola, notamos que tu proceso quedó en pausa.\n\n⏳ Toca el botón de abajo o responde este mensaje para retomar tu verificación y asegurar tus beneficios."),
        "advisor": ("reactivacion_asesor", "👋🏻 Hola, un asesor ha revisado tu caso y está listo para ayudarte.\n\n🧑‍💻 Por favor, toca el botón de abajo para que podamos brindarte atención personalizada."),
        "data_ready": ("reactivacion_datos_listos", "👋🏻 Hola, te informamos que los datos de tu compra ya están registrados en nuestro sistema.\n\n✅ Toca el botón de abajo para iniciar tu proceso de verificación."),
        "collections": ("reactivacion_cobranza", "👋🏻 Hola, nos ponemos en contacto contigo para darle seguimiento al estado de tu cuenta.\n\n 🤝🏻 Si tienes alguna duda con tus pagos o necesitas asistencia, toca el botón de abajo para que un asesor te atienda personalmente."),
    }

    TEMPLATE_BUTTONS = {
        "inactivity": ["Continuar"],
        "advisor": ["Hablar con asesor"],
        "data_ready": ["Iniciar verificación"],
        "collections": ["Tengo una duda"],
    }

    if payload.template_key not in TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Plantilla no válida")
        
    template_name, text_content = TEMPLATE_MAP[payload.template_key]
    button_titles = TEMPLATE_BUTTONS.get(payload.template_key, ["Continuar"])
    extra_json = {
        "interactive": {
            "buttons": [{"title": title} for title in button_titles]
        }
    }

    response = await send_template_message(
        phone=chat.phone,
        template_name=template_name
    )
    provider_message_id = _extract_meta_message_id(response)

    # guardar mensaje
    msg = save_message(
        db=db,
        session_id=session_id,
        phone=chat.phone,
        direction="agent",
        content=text_content, 
        message_id=provider_message_id,
        extra_json=extra_json,
    )
    msg.type = "template" 
    
    now = mexico_now_naive()
    chat.last_message = "Plantilla enviada"
    chat.last_message_at = now
    chat.unread_count = 0
    
    if payload.template_key == "collections":
        from app.core.states.state_types import is_terminal_state
        from app.core.states.states import ChatState
        
        try:
            current_state_enum = ChatState(chat.state)
            if is_terminal_state(current_state_enum) and chat.state != ChatState.COBRANZA.value:
                chat.previous_state = chat.state
                chat.state = ChatState.COBRANZA.value
        except ValueError:
            pass
    
    db.commit()
    db.refresh(msg)
    
    from app.websockets.manager import manager
    await manager.send_to_all(build_new_message_event(chat, msg))
    await manager.send_to_all({
        "type": "dashboard_update",
        "payload": {
            "messages_in_delta": 0,
            "messages_out_delta": 1,
            "session_id": chat.id,
        },
    })
    
    return {"status": "sent"}
