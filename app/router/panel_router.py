from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, WebSocket
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

from app.websockets.manager import manager
from app.db.models import VerificacionCuenta, ChatSessions, Inconsistencias, Message
from app.siga.siga_repository import obtener_venta_por_folio


from app.services.verification_panel_service import (
    classify_panel_status,
    compute_verification,
    group_inconsistencias_by_folio,
    has_open_inconsistencia,
    resolve_cuentas_from_folios,
)



# from app.core.security import verify_api_key  # opcional

router = APIRouter(
    prefix="/api/panel",
    tags=["panel"]
)

# =========================================
# Obtener Mensajes con el websocket
# =========================================

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    import json

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("type") == "typing":
                await manager.send_to_all({
                    "type": "typing",
                    "session_id": payload.get("session_id")
                })

    except:
        manager.disconnect(websocket)

# =========================================
# Panel API: Marcar conversación como leída (RESET UNREAD COUNT)
# =========================================

@router.post("/conversations/{session_id}/read")
def mark_as_read(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

    if session:
        session.unread_count = 0
        db.commit()

    return {"status": "ok"}

@router.post("/conversations/{session_id}/read")
async def mark_as_read(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    session.unread_count = 0
    db.commit()

    await manager.send_to_all({
        "type": "update_unread",
        "session_id": session.id,
        "unread_count": 0
    })

    return {"status": "ok"}

def serialize_inconsistencias(inconsistencias: list[Inconsistencias]) -> list[dict]:
    result: list[dict] = []

    for inc in inconsistencias:
        extra = inc.extra_json or {}
        estatus = inc.estatus or "ABIERTA"

        # 1) Campos normales con mensaje del cliente
        for field_name, field_data in extra.items():
            if not isinstance(field_data, dict):
                continue

            if field_name == "evento":
                continue

            # Caso: campos tipo nombre/domicilio/producto/fecha_venta
            mensaje_cliente = field_data.get("mensaje_cliente")
            confirmado = field_data.get("confirmado")

            if confirmado is False or mensaje_cliente:
                result.append({
                    "campo": field_name,
                    "mensaje": mensaje_cliente or "Sin detalle",
                    "estado": estatus,
                })
                continue

            # Caso: componentes faltantes
            faltantes = field_data.get("faltantes")
            if isinstance(faltantes, list) and faltantes:
                result.append({
                    "campo": field_name,
                    "mensaje": f"Faltantes: {', '.join(str(x) for x in faltantes)}",
                    "estado": estatus,
                })

    return result
def resolve_cuentas_from_folios(folios: list[str], db: Session) -> dict:
    result = {}

    for folio in folios:
        try:
            venta = obtener_venta_por_folio(db, folio)

            if not venta:
                result[folio] = None
                continue

            no_cuenta = getattr(venta, "no_cuenta", None)

            if not no_cuenta:
                result[folio] = None
                continue

            result[folio] = str(no_cuenta)

        except Exception:
            result[folio] = None

    return result

# =========================================
# Endpoints para los dashboard (PAGINADO + DTO + LÓGICA DE NEGOCIO)
# =========================================
@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):

    total_sessions = db.query(ChatSessions).count()

    active_sessions = db.query(ChatSessions)\
        .filter(ChatSessions.last_message_at >= func.now() - text("INTERVAL 1 DAY"))\
        .count()

    total_messages_in = db.query(Message)\
        .filter(Message.direction == "in")\
        .count()

    total_messages_out = db.query(Message)\
        .filter(Message.direction == "out")\
        .count()

    inconsistencias_abiertas = db.query(Inconsistencias)\
        .filter(Inconsistencias.estatus == "abierta")\
        .count()

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "messages_in": total_messages_in,
        "messages_out": total_messages_out,
        "issues_open": inconsistencias_abiertas
    }

# =========================================
# Obtener verificaciones (PAGINADO + DTO + LÓGICA DE NEGOCIO)
# =========================================
@router.get("/verifications")
def get_verifications(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    flow_states = {
        "INCONSISTENCIA",
        "ESCRIBIR_INCONSISTENCIA",
        "FUERA_DE_FLUJO",
        "ACLARACION",
        "LLAMADA",
        "RECORDATORIO_1H",
        "RECORDATORIO_2H",
    }


    valid_statuses = {
        None,
        "in_progress",
        "inconsistent",
        "human_required",
        "stalled",
        "completed",
    }
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="status inválido")

    if limit < 1:
        raise HTTPException(status_code=400, detail="limit inválido")

    if offset < 0:
        raise HTTPException(status_code=400, detail="offset inválido")

    sessions = (
        db.query(ChatSessions)
        .filter(ChatSessions.folio.isnot(None))
        .order_by(ChatSessions.last_message_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = (
        db.query(ChatSessions)
        .filter(ChatSessions.folio.isnot(None))
        .count()
    )
    

    if not sessions:
        return {
            "data": [],
            "total": total,
            "has_more": False,
        }

    folios = [str(session.folio) for session in sessions if session.folio]

    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db)

    no_cuentas = [
        no_cuenta
        for no_cuenta in folio_to_no_cuenta.values()
        if no_cuenta is not None
    ]

    verificaciones = []
    if no_cuentas:
        verificaciones = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta.in_(no_cuentas))
            .all()
        )

    verification_map = {
        str(item.no_cuenta): item
        for item in verificaciones
        if getattr(item, "no_cuenta", None) is not None
    }

    inconsistencias = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.folio.in_(folios))
        .all()
    )

    inconsistencias_by_folio = group_inconsistencias_by_folio(inconsistencias)

    result = []

    for session in sessions:
        folio = str(session.folio)
        no_cuenta = folio_to_no_cuenta.get(folio)

        verification = verification_map.get(no_cuenta) if no_cuenta else None
        progress = verification.json if verification else {}
        verification_data = compute_verification(progress)

        current_step = verification_data["current_step"]

        if session.state in flow_states and session.previous_state:
            current_step = session.previous_state.lower()

        

        inconsistencias_folio = inconsistencias_by_folio.get(folio, [])
        open_inconsistencia = has_open_inconsistencia(inconsistencias_folio)

        panel_status = classify_panel_status(
            verification_data=verification_data,
            has_open_inconsistencia=open_inconsistencia,
            last_activity=session.last_message_at,
            requires_human=False,
        )


        serialized_inconsistencias = serialize_inconsistencias(inconsistencias_folio)

        item = {
            "folio": folio,
            "no_cuenta": no_cuenta,
            "phone": session.phone,
            "status": panel_status,
            "progress_pct": verification_data["progress_pct"],
            "current_step": current_step,
            "inconsistencias": serialized_inconsistencias,
            "inconsistencias_count": len(serialized_inconsistencias),
            "confirmed_count": verification_data["progress_count"],
            "total_steps": verification_data["total_steps"],
            "last_activity": session.last_message_at,
        }

        if status and item["status"] != status:
            continue

        result.append(item)

    return {
        "data": result,
        "total": total,
        "has_more": (offset + limit) < total,
    }
# =========================================
# Obtener conversaciones (PAGINADO + DTO)
# =========================================
@router.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    limit: int = 100,
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
            last_message_at=s.last_message_at,
            unread_count=s.unread_count
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
async def send_agent_message(
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
        await send_whatsapp_message(phone, content)

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

        await manager.send_to_all({
            "type": "new_message",
            "session_id": session.id,
            "message": {
                "content": content,
                "direction": "agent"
            }
        })

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error enviando mensaje a WhatsApp"
        )

    return {"status": "sent"}
