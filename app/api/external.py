from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import ChatSessions
from app.core.states.states import ChatState
from app.adapters.whatsapp_client import send_whatsapp_message
import app.content.messages as msg

router = APIRouter(tags=["External Triggers"])

class NuevaVentaWebhook(BaseModel):
    phone: str  # El teléfono oficial registrado en la venta
    folio: str  # El folio real

from fastapi import APIRouter, Depends, Header, HTTPException, status
from app.config.settings import settings

@router.post("/api/external/ventas/trigger")
async def trigger_verificacion(
    data: NuevaVentaWebhook, 
    x_api_key: str = Header(...),
    db: Session = Depends(get_db)
):
    if x_api_key != settings.EXTERNAL_TRIGGER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate API Key"
        )
    
    # ==========================================
    # CASO 1: ES EL TELÉFONO DEL TITULAR (Busca por teléfono)
    # Permite corregir errores de dedo si el cliente escribió mal el folio
    # ==========================================
    chat = db.query(ChatSessions).filter(
        ChatSessions.phone == data.phone,
        ChatSessions.state == ChatState.ESPERANDO_REGISTRO.value
    ).first()

    if chat:
        import difflib
        similitud = 0.0
        if chat.folio and data.folio:
            similitud = difflib.SequenceMatcher(None, chat.folio.lower(), data.folio.lower()).ratio()
            
        if similitud >= 0.8:
            chat.folio = data.folio # Corrección silenciosa del folio
        else:
            chat = None # Es un folio completamente distinto, ignoramos la coincidencia por teléfono
            
    if not chat:
        # ==========================================
        # CASO 2: ES UN TELÉFONO DIFERENTE (Busca por folio)
        # Un familiar o teléfono prestado metió el folio correcto
        # ==========================================
        chat = db.query(ChatSessions).filter(
            ChatSessions.folio == data.folio,
            ChatSessions.state == ChatState.ESPERANDO_REGISTRO.value
        ).first()

    # ==========================================
    # ACCIÓN: DESPERTAR AL BOT Y PEDIR EL NOMBRE
    # ==========================================
    if chat:
        from app.core.flow.flow import FLOW
        
        chat.state = ChatState.INICIO.value
        db.commit()

        botones_inicio = FLOW.get(ChatState.INICIO, {}).get("buttons", [])
        await send_whatsapp_message(
            phone=chat.phone, 
            text=msg.INICIO.format(folio=chat.folio), 
            buttons=botones_inicio
        )
        
        return {"status": "success", "message": "Sesión despertada y reto de seguridad enviado."}

    # Si nadie estaba esperando ni por teléfono ni por folio:
    return {"status": "ignored", "message": "Ninguna sesión en espera."}