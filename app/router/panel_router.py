from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
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
from app.security.auth_service import decode_panel_session, restrict_to_assigned
from app.services.verification_service import VerificationService
from app.websockets.manager import manager
from app.db.models import VerificacionCuenta, ChatSessions, Inconsistencias, Message, FlowEvent
from app.siga.siga_repository import obtener_venta_por_folio
from app.security.auth_dependencies import get_current_panel_user
from app.adapters.whatsapp_client import send_whatsapp_media
from fastapi import Request
from app.services.verification_tracker import STEP_MAP
from app.utils.inconsistencias_serializer import serialize_inconsistencias
from app.services.verification_panel_service import (
    classify_panel_status,
    compute_verification,
    group_inconsistencias_by_folio,
    has_open_inconsistencia,
)
from app.db.models import BitacoraVentas

# ORDEN REAL DEL FLOW 
FUNNEL_STEPS = [
    "folio",
    "nombre",
    "domicilio",
    "fecha",
    "producto",
    "componentes",
    "pagoInicial",
    "pagos",
    "bancos",
    "plan3meses",
    "planes",
    "beneficios",
    "finalizado",
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

    session_token = websocket.cookies.get("panel_session")

    if not session_token:
        await websocket.close(code=1008)
        return

    # crear sesión DB manual
    db = next(get_db())

    try:
        user = decode_panel_session(session_token, db)  
    except Exception:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    websocket.state.user = user

    import json

    try:
        manager.connect(websocket)

        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("type") == "typing":
                await manager.send_to_all({
                    "type": "typing",
                    "session_id": payload.get("session_id")
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket)

    except Exception:
        manager.disconnect(websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        db.close()  #importante
# =========================================
# Panel API: Marcar conversación como leída (RESET UNREAD COUNT)
# =========================================

@router.post("/conversations/{session_id}/read")
async def mark_as_read(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    session.unread_count = 0
    db.commit()

    await manager.send_to_all({
        "type": "update_unread",
        "session_id": session.id,
        "unread_count": 0
    })

    return {"status": "ok"}

def resolve_cuentas_from_folios(folios: list[str], db: Session, user) -> dict:
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")
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
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    # --------------------------------------
    # 🧠 FILTRO DE TIEMPO
    # --------------------------------------
    date_from = datetime.utcnow() - timedelta(days=days)

    # --------------------------------------
    #  SUBQUERY: ordenar eventos por sesión
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
    #  AGREGAR MÉTRICAS
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
    #  ORDENAR POR TIEMPO PROMEDIO (cuellos de botella)
    # --------------------------------------
    result_sorted = sorted(result, key=lambda x: x["avg_seconds"], reverse=True)

    return {
        "range_days": days,
        "data": result_sorted
    }
@router.get("/dashboard/funnel")
def dashboard_funnel(
    days: int = 7,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    date_from = datetime.utcnow() - timedelta(days=days)

    events = (
        db.query(
            FlowEvent.session_id,
            FlowEvent.to_state,
            FlowEvent.created_at
        )
        .filter(
            FlowEvent.to_state.isnot(None),
            FlowEvent.created_at >= date_from
        )
        .all()
    )

    # --------------------------------------
    # NORMALIZAR A STEPS
    # --------------------------------------
    session_steps = {}

    for e in events:
        step = STEP_MAP.get(e.to_state)

        if not step:
            continue

        if e.session_id not in session_steps:
            session_steps[e.session_id] = {}

        # guardar primera vez que llegó al step
        if step not in session_steps[e.session_id]:
            session_steps[e.session_id][step] = e.created_at

    # --------------------------------------
    # CONTAR USUARIOS POR STEP
    # --------------------------------------
    step_counts = {step: 0 for step in FUNNEL_STEPS}

    for steps in session_steps.values():
        for step in steps.keys():
            step_counts[step] += 1

    # --------------------------------------
    # CONSTRUIR FUNNEL ORDENADO
    # --------------------------------------
    funnel = []

    for step in FUNNEL_STEPS:
        funnel.append({
            "step": step,
            "total": step_counts.get(step, 0)
        })

    # --------------------------------------
    # DROP-OFF
    # --------------------------------------
    for i in range(len(funnel)):
        current = funnel[i]["total"]
        next_val = funnel[i + 1]["total"] if i + 1 < len(funnel) else 0

        funnel[i]["drop_off"] = max(current - next_val, 0)
        funnel[i]["conversion_pct"] = round(
            (next_val / current * 100) if current > 0 else 0,
            2
        )

    return {
        "range_days": days,
        "data": funnel
    }

@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),):

    total_sessions = db.query(func.count(ChatSessions.id)).scalar()

    active_sessions = db.query(func.count(ChatSessions.id))\
        .filter(ChatSessions.last_message_at >= func.now() - text("INTERVAL 1 DAY"))\
        .scalar()

    total_messages_in = db.query(func.count(Message.id))\
        .filter(Message.direction == "in")\
        .scalar()

    total_messages_out = db.query(func.count(Message.id))\
        .filter(Message.direction.in_(["out", "agent"]))\
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
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    # =========================
    # 🔐 VALIDACIONES
    # =========================
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    valid_statuses = {
        None,
        "in_progress",
        "inconsistent",
        "human_required",
        "stalled",
        "completed",
    }

    if status not in valid_statuses:
        raise HTTPException(400, "status inválido")

    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit inválido")

    if offset < 0:
        raise HTTPException(400, "offset inválido")

    # =========================
    # 📦 OBTENER SESIONES
    # =========================
    
    sessions = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .filter(ChatSessions.folio.isnot(None))
        .order_by(ChatSessions.last_message_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    

    total = (
        restrict_to_assigned(db.query(func.count(ChatSessions.id)), user, db)
        .filter(ChatSessions.folio.isnot(None))
        .scalar()
    )

    if not sessions:
        return {
            "data": [],
            "total": total,
            "has_more": False,
        }

    # =========================
    # 🧠 HELPERS
    # =========================
    def normalize_phone(phone: str | None) -> str:
        if not phone:
            return ""
        phone = str(phone).replace("+", "").strip()
        if phone.startswith("52") and len(phone) > 10:
            phone = phone[2:]
        return phone[-10:]
    
    def build_siga_url(no_cuenta: str | None, folio: str | None) -> str | None:
        if no_cuenta:
            return f"https://siga.mxcomp.com.mx/cuentas/{no_cuenta}"

        if folio:
            return f"https://siga.mxcomp.com.mx/ventas/{folio}"

        return None

    # =========================
    # 📞 RESOLVER NOMBRES (BATCH)
    # =========================
    normalized_phones = list({
        normalize_phone(s.phone)
        for s in sessions
        if s.phone
    })

    ventas = (
        restrict_to_assigned(db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo), user, db)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == 1
        )
        .all()
    )

    phone_to_name = {}
    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_phone(v.tel_1)
        if db_phone and v.nombre_completo:
            phone_to_name[db_phone] = v.nombre_completo.strip()

    # =========================
    # 🔗 FOLIOS → CUENTAS
    # =========================
    folios = [str(s.folio) for s in sessions if s.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    no_cuentas = [
        nc for nc in folio_to_no_cuenta.values() if nc is not None
    ]

    verificaciones = []
    if no_cuentas:
        verificaciones = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta.in_(no_cuentas))
            .all()
        )

    verification_map = {
        str(v.no_cuenta): v
        for v in verificaciones
        if v.no_cuenta
    }

    # =========================
    # ⚠️ INCONSISTENCIAS (BATCH)
    # =========================
    inconsistencias = (
        restrict_to_assigned(db.query(Inconsistencias), user, db)
        .filter(Inconsistencias.folio.in_(folios))
        .all()
    )

    inconsistencias_by_folio = group_inconsistencias_by_folio(inconsistencias)

    # =========================
    # 🔄 ARMADO FINAL
    # =========================
    result = []

    flow_states = {
        "INCONSISTENCIA",
        "ESCRIBIR_INCONSISTENCIA",
        "FUERA_DE_FLUJO",
        "ACLARACION",
        "LLAMADA",
        "RECORDATORIO_1H",
        "RECORDATORIO_2H",
    }
    

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
            "name": phone_to_name.get(normalize_phone(session.phone)),
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
            "siga_url": build_siga_url(no_cuenta, folio),
        }

        if status and item["status"] != status:
            continue

        result.append(item)

    return {
        "data": result,
        "total": total,
        "has_more": (offset + limit) < total,
    }
@router.get("/verifications/{session_id}")
def get_verification_by_session(
    session_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
):
    # =========================
    # 🔐 VALIDACIÓN
    # =========================
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not session or not session.folio:
        raise HTTPException(404, "Verificación no encontrada")

    folio = str(session.folio)

    # =========================
    # 🧠 RESOLVER no_cuenta
    # =========================
    service = VerificationService(db)

    no_cuenta = service.resolve_no_cuenta_from_folio(str(session.folio)) if session.folio else None


    # =========================
    # 🧾 VERIFICACIÓN
    # =========================
    verification = None
    progress = {}

    if no_cuenta:
        verification = (
            db.query(VerificacionCuenta)
            .filter(VerificacionCuenta.no_cuenta == no_cuenta)
            .first()
        )

    if verification:
        progress = verification.json or {}

    verification_data = compute_verification(progress)

    # =========================
    # ⚠️ INCONSISTENCIAS
    # =========================
    inconsistencias = (
        db.query(Inconsistencias)
        .filter(Inconsistencias.folio == folio)
        .all()
    )

    serialized_inconsistencias = serialize_inconsistencias(inconsistencias)

    open_inconsistencia = any(
        i["estado"] == "ABIERTA" for i in serialized_inconsistencias
    )

    # =========================
    # 📊 STATUS
    # =========================
    panel_status = classify_panel_status(
        verification_data=verification_data,
        has_open_inconsistencia=open_inconsistencia,
        last_activity=session.last_message_at,
        requires_human=False,
    )

    # =========================
    # 🧠 STEP CORRECTO
    # =========================
    current_step = verification_data["current_step"]

    flow_states = {
        "INCONSISTENCIA",
        "ESCRIBIR_INCONSISTENCIA",
        "FUERA_DE_FLUJO",
        "ACLARACION",
        "LLAMADA",
        "RECORDATORIO_1H",
        "RECORDATORIO_2H",
    }

    if session.state in flow_states and session.previous_state:
        current_step = session.previous_state.lower()

    # =========================
    # 📦 RESPONSE FINAL
    # =========================
    return {
        "session_id": session.id,
        "folio": folio,
        "name": None,  # opcional: puedes resolverlo igual que conversations
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
# =========================================
# Obtener conversaciones (PAGINADO + DTO)
# =========================================
@router.get("/conversations", response_model=list[ConversationResponse])
def get_conversations(
    limit: int = 10000,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),
    # _: str = Depends(verify_api_key)
):
    if limit > 100:
        limit = 100

    sessions = (
        restrict_to_assigned(db.query(ChatSessions), user, db)
        .order_by(desc(ChatSessions.last_message_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    def normalize_phone(phone: str | None) -> str:
        if not phone:
            return ""

        phone = str(phone).replace("+", "").strip()

        if phone.startswith("52") and len(phone) > 10:
            phone = phone[2:]

        return phone[-10:]
    
    # teléfonos normalizados de sesiones
    normalized_phones = list({
        normalize_phone(s.phone)
        for s in sessions
        if s.phone
    })

    # QUERY MASIVA
    ventas = (
        db.query(BitacoraVentas.tel_1, BitacoraVentas.nombre_completo)
        .filter(
            func.right(BitacoraVentas.tel_1, 10).in_(normalized_phones),
            BitacoraVentas.id_emp_bv == 1
        )
        .all()
    )

    folios = [str(s.folio) for s in sessions if s.folio]
    folio_to_no_cuenta = resolve_cuentas_from_folios(folios, db, user)

    phone_to_name = {}

    for v in ventas:
        if not v.tel_1:
            continue

        db_phone = normalize_phone(v.tel_1)
        if db_phone and v.nombre_completo:
            phone_to_name[db_phone] = v.nombre_completo.strip()

    return [
        ConversationResponse(
            id=s.id,
            phone=s.phone,
            name=phone_to_name.get(normalize_phone(s.phone)),
            last_message=s.last_message,
            last_message_at=s.last_message_at,
            unread_count=s.unread_count,
            no_cuenta=folio_to_no_cuenta.get(str(s.folio)) if s.folio else None,
            folio=str(s.folio) if s.folio else None
        )
        for s in sessions
    ]


# =========================================
# Obtener mensajes (PAGINADO REAL)
# =========================================
@router.get("/messages/{session_id}", response_model=PaginatedMessagesResponse)
def get_messages(
    session_id: int,
    limit: int = 10000,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user),

    # _: str = Depends(verify_api_key)
):
    MAX_MESSAGES = 250
    limit = min(limit, MAX_MESSAGES)

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .first()
    )

    if not session:
        raise HTTPException(404, "La sesión no existe")
    # evita acceso cruzado
    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    base_query = db.query(Message).filter(
        Message.session_id == session_id
    )

    total = base_query.count()

    messages = (
        base_query
        .order_by(desc(Message.id))
        .offset(offset)
        .limit(limit)
        .all()
    )
    messages.reverse()

    return PaginatedMessagesResponse(
        data=[
            MessageResponse(
                id=m.id,
                direction=m.direction,
                content=m.content,
                created_at=m.created_at,
                type=m.type,
                media_url=m.media_url,
                file_name=m.file_name
            )
            for m in messages
        ],
        total=total,
        has_more = total > limit
    )




# =========================================
# Enviar mensaje desde panel (SEGURO + CONSISTENTE)
# =========================================
@router.post("/messages")
async def send_agent_message(
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    user = Depends(get_current_panel_user)
):
    content = payload.content.strip()
    print("🧨 TEXTO QUE VOY A ENVIAR:", repr(content))

    if not content:
        raise HTTPException(400, "Mensaje vacío")

    if len(content) > 1000:
        raise HTTPException(400, "Mensaje demasiado largo")

    if user.empresa_id != 1:
        raise HTTPException(403, "No autorizado")

    session = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == payload.session_id)
        .first()
    )

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    phone = session.phone

    try:
        await send_whatsapp_message(phone, content)

        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content
        )

        db.add(message)

        now = datetime.utcnow()
        session.last_message_at = now
        session.last_message = content

        db.flush()

        message_payload = {
            "id": message.id,
            "content": message.content,
            "direction": message.direction,
            "created_at": message.created_at.isoformat() if message.created_at else now.isoformat()
        }

        db.commit()

        await manager.send_to_all({
            "type": "new_message",
            "session_id": session.id,
            "message": message_payload
        })

        await manager.send_to_all({
            "type": "dashboard_update",
            "payload": {
                "messages_in_delta": 0,
                "messages_out_delta": 1,
            },
        })

        await manager.send_to_all({
            "type": "verification_update",
            "payload": {
                "session_id": session.id,
                "last_activity": now.isoformat(),
            }
        })

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error enviando mensaje a WhatsApp"
        )

    return {"status": "sent"}
@router.post("/messages/file")
async def send_agent_file(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.json()

    print("📦 PAYLOAD:", payload)

    session_id = payload.get("session_id")
    media_url = payload.get("media_url")
    file_name = payload.get("file_name")
    media_type = payload.get("type")

    if not session_id or not media_url or not media_type:
        raise HTTPException(400, "Datos incompletos")

    session = db.query(ChatSessions).filter(ChatSessions.id == session_id).first()

    if not session:
        raise HTTPException(404, "Sesión no encontrada")

    phone = session.phone

    # =========================
    # 💾 1. GUARDAR PRIMERO
    # =========================
    content = payload.get("content")

    # 🚫 NO generar [MEDIA]
    if not content or content == "[MEDIA]":
        content = " "

    try:
        message = Message(
            session_id=session.id,
            phone=phone,
            direction="agent",
            content=content,
            type=media_type,
            media_url=media_url,
            file_name=file_name
        )

        db.add(message)
        session.last_message_at = datetime.utcnow()

        db.commit()
        db.refresh(message)

        print("✅ GUARDADO EN DB:", message.id)

    except Exception as e:
        db.rollback()
        print("❌ ERROR DB:", e)
        raise HTTPException(500, "Error guardando mensaje")

    # =========================
    # 📡 2. WEBSOCKET (INMEDIATO)
    # =========================
    await manager.send_to_all({
        "type": "new_message",
        "session_id": session.id,
        "message": {
            "id": message.id,
            "content": message.content,
            "direction": "agent",
            "type": media_type,
            "media_url": media_url,
            "file_name": file_name,
            "created_at": message.created_at.isoformat()
        }
    })

    # =========================
    # 📤 3. WHATSAPP (ASYNC)
    # =========================
    async def send_media_safe():
        try:
            print("📤 ENVIANDO MEDIA A WHATSAPP:", media_url)

            caption = message.content if message.content else None

            await send_whatsapp_media(
                phone=phone,
                media_url=media_url,
                media_type=media_type,
                caption=caption,
                filename=file_name
            )

        except Exception as e:
            print("❌ ERROR WHATSAPP:", e)

    import asyncio
    asyncio.create_task(send_media_safe())

    return {"status": "sent"}