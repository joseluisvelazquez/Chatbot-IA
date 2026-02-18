from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.config.settings import (
    VERIFY_TOKEN,
)

from app.services.meta_parser import parse_meta_payload
from app.services.meta_sender import send_text, send_buttons

from app.services.session_service import (
    get_or_create_session,
    update_session,
)

from app.core.flow_engine import process_message


router = APIRouter()


# ============================================================
# VERIFICACIÓN DEL WEBHOOK 
# ============================================================
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Endpoint requerido por Meta para verificar el webhook.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


# ============================================================
# RECEPCIÓN DE MENSAJES DESDE META
# ============================================================
@router.post("/webhook")
async def receive_webhook(request: Request):
    """
    Recibe eventos reales de WhatsApp Cloud API.
    """

    try:
        payload = await request.json()
    except Exception:
        # Si no se puede leer JSON, igual responder 200 para no romper webhook
        return {"status": "ok"}

    # --------------------------------------------------------
    # 🔹 1. Parsear payload crudo de Meta
    # --------------------------------------------------------
    parsed = parse_meta_payload(payload)

    #print("PARSED:", parsed)

    # Si no hay mensaje relevante o es status → ignorar
    if not parsed or parsed.get("is_status"):
        return {"status": "ok"}

    phone = parsed.get("phone")
    text = parsed.get("text")
    button_id = parsed.get("button_id")

    if not phone:
        return {"status": "ok"}

    # --------------------------------------------------------
    # 2. Obtener o crear sesión desde BD
    # --------------------------------------------------------
    session = get_or_create_session(phone)

    # --------------------------------------------------------
    # 3. Procesar mensaje con el motor conversacional
    # --------------------------------------------------------
    try:
        reply, next_state, buttons, previous_state = process_message(
            session=session,
            text=text,
            intent=button_id,
        )
        #print("REPLY:", reply)
        #print("NEXT_STATE:", next_state)
        #print("BUTTONS:", buttons)

    except Exception as e:
        # Si algo falla en el core, no romper el webhook
        # Puedes loggear aquí si quieres
        return {"status": "ok"}

    # --------------------------------------------------------
    # 4. Persistir nuevo estado
    # --------------------------------------------------------
    try:
        update_session(
            session_id=session.id,
            state=next_state.value,
            last_message=text,
            previous_state=previous_state or session.previous_state,
        )
    except Exception:
        # Si falla la BD, no romper webhook
        pass

    # --------------------------------------------------------
    # 5. Enviar respuesta a WhatsApp
    # --------------------------------------------------------
    try:
        if buttons:
            await send_buttons(phone, reply, buttons)
        else:
            await send_text(phone, reply)
    except Exception:
        # Si falla envío a Meta, no romper webhook
        pass

    # Meta solo necesita 200 OK
    return {"status": "ok"}
