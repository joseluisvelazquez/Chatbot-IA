from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc, func, text
from datetime import datetime, timedelta

from app.schemas.panel import (
    SendMessageRequest,
    ConversationResponse,
    MessageResponse,
    PaginatedMessagesResponse
)

from app.adapters.whatsapp_client import send_whatsapp_message
from app.db.session import get_db
from app.websockets.manager import manager
from app.db.models import VerificacionCuenta, ChatSessions, Inconsistencias, Message, FlowEvent
from app.siga.siga_repository import obtener_venta_por_folio


from app.services.verification_panel_service import (
    classify_panel_status,
    compute_verification,
    group_inconsistencias_by_folio,
    has_open_inconsistencia,
    resolve_cuentas_from_folios,
)

# ORDEN REAL DEL FLOW (ajústalo si cambias estados)
FUNNEL_ORDER = [
    "INICIO",
    "CONFIRMAR_FOLIO",
    "CONFIRMAR_NOMBRE",
    "CONFIRMAR_DOMICILIO",
    "CONFIRMAR_FECHA",
    "CONFIRMAR_PRODUCTO",
    "CONFIRMAR_ESTADO_PRODUCTO",
    "CONFIRMAR_COMPONENTES",
    "COMPONENTES_FALTANTES",
    "CONFIRMAR_PAGO_INICIAL",
    "INFO_PAGOS",
    "INFO_METODOS_PAGO",
    "INFO_PLAN_3_MESES",
    "INFO_BENEFICIOS",
    "FINALIZADO",
]
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

@router.get("/dashboard/state-times")
def dashboard_state_times(
    days: int = 7,
    db: Session = Depends(get_db)
):
    # --------------------------------------
    # 🧠 FILTRO DE TIEMPO
    # --------------------------------------
    date_from = datetime.utcnow() - timedelta(days=days)

    # --------------------------------------
    # 🔥 SUBQUERY: ordenar eventos por sesión
    # --------------------------------------
    events = (
        db.query(
            FlowEvent.session_id,
            FlowEvent.from_state,
            FlowEvent.to_state,
            FlowEvent.created_at
        )
        .filter(
            FlowEvent.created_at >= date_from,
            FlowEvent.from_state.isnot(None),
            FlowEvent.to_state.isnot(None),
        )
        .order_by(FlowEvent.session_id, FlowEvent.created_at)
        .all()
    )

    # --------------------------------------
    # 🧠 CALCULAR TIEMPOS ENTRE TRANSICIONES
    # --------------------------------------
    transitions = {}

    last_event_per_session = {}

    for e in events:
        session_id = e.session_id

        if session_id in last_event_per_session:
            prev = last_event_per_session[session_id]

            # transición real
            key = f"{prev.to_state} → {e.to_state}"

            time_diff = (e.created_at - prev.created_at).total_seconds()

            if key not in transitions:
                transitions[key] = {
                    "from_state": prev.to_state,
                    "to_state": e.to_state,
                    "times": []
                }

            # evitar tiempos absurdos
            if 0 < time_diff < 86400:  # max 24h
                transitions[key]["times"].append(time_diff)

        last_event_per_session[session_id] = e

    # --------------------------------------
    # 🔥 AGREGAR MÉTRICAS
    # --------------------------------------
    result = []

    for key, data in transitions.items():
        times = data["times"]

        if not times:
            continue

        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)

        result.append({
            "transition": key,
            "from_state": data["from_state"],
            "to_state": data["to_state"],
            "count": len(times),
            "avg_seconds": round(avg_time, 2),
            "avg_minutes": round(avg_time / 60, 2),
            "max_minutes": round(max_time / 60, 2),
            "min_minutes": round(min_time / 60, 2),
        })

    # --------------------------------------
    # 🔥 ORDENAR POR TIEMPO PROMEDIO (cuellos de botella)
    # --------------------------------------
    result_sorted = sorted(result, key=lambda x: x["avg_seconds"], reverse=True)

    return {
        "range_days": days,
        "data": result_sorted
    }

@router.get("/dashboard/funnel")
def dashboard_funnel(
    days: int = 7,  # 🔥 filtro de tiempo (últimos N días)
    db: Session = Depends(get_db)
):
    # --------------------------------------
    #  FILTRO DE TIEMPO
    # --------------------------------------
    date_from = datetime.utcnow() - timedelta(days=days)

    # --------------------------------------
    #  SUBQUERY: PRIMERA VEZ POR ESTADO
    # --------------------------------------
    subquery = (
        db.query(
            FlowEvent.session_id,
            FlowEvent.to_state,
            func.min(FlowEvent.created_at).label("first_time")
        )
        .filter(
            FlowEvent.to_state.isnot(None),
            FlowEvent.created_at >= date_from
        )
        .group_by(FlowEvent.session_id, FlowEvent.to_state)
        .subquery()
    )

    # --------------------------------------
    #  AGREGACIÓN FINAL
    # --------------------------------------
    results = (
        db.query(
            subquery.c.to_state,
            func.count(func.distinct(subquery.c.session_id)).label("total")
        )
        .group_by(subquery.c.to_state)
        .all()
    )

    # --------------------------------------
    #  MAPA PARA ACCESO RÁPIDO
    # --------------------------------------
    result_map = {r.to_state: r.total for r in results}

    # --------------------------------------
    #  ORDENAR SEGÚN FLUJO
    # --------------------------------------
    funnel = []

    for state in FUNNEL_ORDER:
        funnel.append({
            "state": state,
            "total": result_map.get(state, 0)
        })

    # --------------------------------------
    #  DROP-OFF (SUPER IMPORTANTE)
    # --------------------------------------
    for i in range(len(funnel)):
        current = funnel[i]["total"]
        next_val = funnel[i + 1]["total"] if i + 1 < len(funnel) else 0

        drop_off = current - next_val if current > 0 else 0
        conversion = (next_val / current * 100) if current > 0 else 0

        funnel[i]["drop_off"] = drop_off
        funnel[i]["conversion_pct"] = round(conversion, 2)

    return {
        "range_days": days,
        "data": funnel
    }

@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):

    total_sessions = db.query(func.count(ChatSessions.id)).scalar()

    active_sessions = db.query(func.count(ChatSessions.id))\
        .filter(ChatSessions.last_message_at >= func.now() - text("INTERVAL 1 DAY"))\
        .scalar()

    total_messages_in = db.query(func.count(Message.id))\
        .filter(Message.direction == "in")\
        .scalar()

    total_messages_out = db.query(func.count(Message.id))\
        .filter(Message.direction == "out")\
        .scalar()

    inconsistencias_abiertas = db.query(func.count(Inconsistencias.id))\
        .filter(Inconsistencias.estatus == "abierta")\
        .scalar()

    return {
        "total_sessions": total_sessions or 0,
        "active_sessions": active_sessions or 0,
        "messages_in": total_messages_in or 0,
        "messages_out": total_messages_out or 0,
        "issues_open": inconsistencias_abiertas or 0
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
            "session_id": session.id,
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
