from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import ChatSessions, ChatTechnicalLog, ChatTransferAudit
from app.security.rbac import (
    ROLE_ADMIN,
    ROLE_GESTOR_COBRANZA,
    ROLE_JEFE_OPERATIVO,
    ROLE_SOPORTE_TECNICO,
    can_assign_manager_chat,
    can_close_support_chat,
    can_escalate_chat,
    can_release_chat,
    can_reply_chat,
    can_return_to_assistant_chat,
    can_take_chat,
    can_transfer_to_support_chat,
    can_view_chat,
    ensure_can_view_chat,
    has_permission,
    is_test_phone,
    normalize_role,
    status_for_role,
)
from app.services.panel_events import emit_domain_event
from app.services.panel_staff import (
    get_active_staff_member,
    get_default_inactive_manager_destination,
    is_manager_active,
    is_panel_user_available as panel_user_available,
    normalize_username,
)


OWNER_ASSISTANT = "assistant"
OWNER_USER = "user"

STATUS_UNASSIGNED = "unassigned"
STATUS_ASSISTANT_ACTIVE = "assistant_active"
STATUS_ASSIGNED_GESTOR = "assigned_gestor"
STATUS_ASSIGNED_SOPORTE = "assigned_soporte"
STATUS_ESCALATED = "escalated"
STATUS_CLOSED = "closed"
DEFAULT_TECHNICAL_SLA_MINUTES = 240

TECHNICAL_KEYWORDS = [
    "pantalla azul",
    "virus",
    "wifi",
    "impresora",
    "office",
    "correo",
    "no abre",
    "licencia",
    "no prende",
    "falla pantalla",
    "no sirve teclado",
    "garantia",
    "garantía",
    "formateo",
    "internet",
    "lenta",
    "error sistema",
    "no instala",
    "se trabo",
    "se trabó",
    "software",
    "hardware",
    "instalacion",
    "instalación",
]


@dataclass(frozen=True)
class OperationResult:
    chat: ChatSessions
    event: object
    before_chat: dict | None = None
    notification_target_user: str | None = None
    notification_target_role: str | None = None


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def detect_technical_keyword(text: str | None) -> str | None:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return None

    return next((keyword for keyword in TECHNICAL_KEYWORDS if keyword in normalized), None)


def is_technical_message(text: str | None) -> bool:
    return detect_technical_keyword(text) is not None


def initialize_operational_defaults(chat: ChatSessions) -> None:
    if chat.owner_type is None:
        chat.owner_type = OWNER_ASSISTANT
    if chat.status_operativo is None:
        chat.status_operativo = STATUS_ASSISTANT_ACTIVE
    if chat.priority is None:
        chat.priority = "normal"
    if chat.test_mode is None:
        chat.test_mode = is_test_phone(chat.phone)
    elif not chat.test_mode and is_test_phone(chat.phone):
        chat.test_mode = True


def lock_chat(db: Session, session_id: int) -> ChatSessions:
    chat = (
        db.query(ChatSessions)
        .filter(ChatSessions.id == session_id)
        .with_for_update()
        .first()
    )
    if not chat:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesion no encontrada")
    initialize_operational_defaults(chat)
    return chat


def _snapshot(chat: ChatSessions) -> dict:
    return {
        "id": chat.id,
        "phone": chat.phone,
        "test_mode": bool(chat.test_mode),
        "owner_type": chat.owner_type,
        "assigned_user_id": chat.assigned_user_id,
        "assigned_role": chat.assigned_role,
        "status_operativo": chat.status_operativo,
        "previous_owner_user_id": chat.previous_owner_user_id,
        "previous_owner_role": chat.previous_owner_role,
    }


def _audit_transfer(
    db: Session,
    *,
    chat: ChatSessions,
    action: str,
    actor,
    before: dict,
    reason: str | None = None,
) -> ChatTransferAudit:
    audit = ChatTransferAudit(
        session_id=chat.id,
        action=action,
        actor_username=str(getattr(actor,"username",None) or ""),
        actor_role=normalize_role(getattr(actor, "role", None)),
        from_owner_type=before.get("owner_type"),
        from_assigned_user_id=before.get("assigned_user_id"),
        from_assigned_role=before.get("assigned_role"),
        from_status=before.get("status_operativo"),
        to_owner_type=chat.owner_type,
        to_assigned_user_id=chat.assigned_user_id,
        to_assigned_role=chat.assigned_role,
        to_status=chat.status_operativo,
        reason=reason,
        created_at=utcnow_naive(),
    )
    db.add(audit)
    db.flush()
    return audit


def _operation_payload(chat: ChatSessions, action: str, reason: str | None = None) -> dict:
    return {
        "session_id": chat.id,
        "phone": chat.phone,
        "action": action,
        "owner_type": chat.owner_type,
        "assigned_user_id": chat.assigned_user_id,
        "assigned_role": chat.assigned_role,
        "status_operativo": chat.status_operativo,
        "priority": chat.priority,
        "transfer_pending": bool(chat.transfer_pending),
        "returned_from_role": chat.returned_from_role,
        "transferred_by_user_id": chat.transferred_by_user_id,
        "previous_owner_user_id": chat.previous_owner_user_id,
        "previous_owner_role": chat.previous_owner_role,
        "transfer_reason": chat.transfer_reason,
        "transfer_created_at": chat.transfer_created_at.isoformat() if chat.transfer_created_at else None,
        "reason": reason,
    }


def _emit_operation_event(db: Session, chat: ChatSessions, actor, action: str, reason: str | None = None):
    return emit_domain_event(
        db,
        event_type=f"chat.{action}",
        aggregate_type="chat_session",
        aggregate_id=chat.id,
        actor=actor,
        payload=_operation_payload(chat, action, reason),
    )


def _can_mutate_owned(chat: ChatSessions, actor) -> bool:
    if normalize_role(getattr(actor, "role", None)) in {ROLE_ADMIN, ROLE_JEFE_OPERATIVO}:
        return True
    if not can_view_chat(chat, actor):
        return False
    return bool(chat.assigned_user_id and chat.assigned_user_id == getattr(actor, "username", None))


def _has_open_technical_incident(db: Session, session_id: int) -> bool:
    return bool(
        db.query(ChatTechnicalLog.id)
        .filter(
            ChatTechnicalLog.session_id == session_id,
            ChatTechnicalLog.status == "open",
        )
        .first()
    )


def _empresa_id_for_actor(actor) -> int:
    try:
        return int(getattr(actor, "empresa_id", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _validate_destination_user(
    db: Session,
    *,
    actor,
    destination: str,
    destination_user_id: str | None,
) -> str | None:
    normalized_destination = str(destination or "").strip().lower()
    normalized_username = normalize_username(destination_user_id)

    if not normalized_username:
        return None

    expected_role = None
    if normalized_destination in {"gestor", "gestor_cobranza"}:
        expected_role = ROLE_GESTOR_COBRANZA
    elif normalized_destination in {"soporte", "soporte_tecnico"}:
        expected_role = ROLE_SOPORTE_TECNICO

    if expected_role:
        row = get_active_staff_member(
            db,
            username=normalized_username,
            empresa_id=_empresa_id_for_actor(actor),
            expected_role=expected_role,
        )
        return normalize_username(row.nombre_usuario)

    return normalized_username


def _ensure_can_take(chat: ChatSessions, actor) -> None:
    ensure_can_view_chat(chat, actor)
    if not can_take_chat(chat, actor):
        actor_role = normalize_role(getattr(actor, "role", None))
        if actor_role not in {
            ROLE_ADMIN,
            ROLE_JEFE_OPERATIVO,
            ROLE_GESTOR_COBRANZA,
            ROLE_SOPORTE_TECNICO,
        }:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")
        if chat.status_operativo == STATUS_CLOSED:
            raise HTTPException(status.HTTP_409_CONFLICT, "La conversacion esta cerrada")
        if chat.assigned_user_id and chat.assigned_user_id != getattr(actor, "username", None):
            raise HTTPException(status.HTTP_409_CONFLICT, "La conversacion ya tiene owner")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")


def _ensure_can_transfer(chat: ChatSessions, actor, destination: str, db: Session) -> None:
    ensure_can_view_chat(chat, actor)
    destination = str(destination or "").strip().lower()

    if chat.status_operativo == STATUS_CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "La conversacion esta cerrada")

    if (
        chat.status_operativo == STATUS_ASSIGNED_SOPORTE
        and destination in {"assistant", "assistant_active", "gestor", "gestor_cobranza", "cola_general"}
        and _has_open_technical_incident(db, chat.id)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cierra la incidencia tecnica antes de mover el chat fuera de soporte",
        )

    if destination in {"soporte", "soporte_tecnico"}:
        if can_transfer_to_support_chat(chat, actor):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    if destination in {"assistant", "assistant_active"}:
        if can_return_to_assistant_chat(chat, actor):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    if destination in {"gestor", "gestor_cobranza"}:
        if can_assign_manager_chat(chat, actor) or (
            chat.status_operativo == STATUS_ASSIGNED_SOPORTE and can_close_support_chat(chat, actor)
        ):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    if destination == "jefe_operativo":
        if can_escalate_chat(chat, actor):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    if destination == "cola_general":
        if can_release_chat(chat, actor):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Destino invalido")


def tomar_chat(
    db: Session,
    *,
    session_id: int,
    actor,
    target_role: str | None = None,
) -> OperationResult:
    chat = lock_chat(db, session_id)
    _ensure_can_take(chat, actor)

    role = normalize_role(target_role or getattr(actor, "role", None))
    if role not in {ROLE_GESTOR_COBRANZA, ROLE_SOPORTE_TECNICO, ROLE_JEFE_OPERATIVO}:
        role = normalize_role(getattr(actor, "role", None))

    before = _snapshot(chat)
    now = utcnow_naive()
    chat.owner_type = OWNER_USER
    chat.assigned_user_id = getattr(actor, "username", None)
    chat.assigned_role = role
    chat.status_operativo = status_for_role(role)
    chat.assigned_at = now
    chat.locked_until = None
    chat.transfer_pending = False
    chat.updated_at = now

    _audit_transfer(db, chat=chat, action="take", actor=actor, before=before)
    event = _emit_operation_event(db, chat, actor, "take")
    return OperationResult(
        chat=chat,
        event=event,
        before_chat=before,
        notification_target_user=chat.assigned_user_id,
    )


def liberar_chat(
    db: Session,
    *,
    session_id: int,
    actor,
    reason: str | None = None,
) -> OperationResult:
    chat = lock_chat(db, session_id)
    if not can_release_chat(chat, actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    before = _snapshot(chat)
    chat.returned_from_role = chat.assigned_role
    chat.owner_type = None
    chat.assigned_user_id = None
    chat.assigned_role = None
    chat.status_operativo = STATUS_UNASSIGNED
    chat.assigned_at = None
    chat.locked_until = None
    chat.transfer_pending = False
    chat.transferred_by_user_id = None
    chat.transfer_reason = None
    chat.transfer_created_at = None
    chat.updated_at = utcnow_naive()

    _audit_transfer(db, chat=chat, action="release", actor=actor, before=before, reason=reason)
    event = _emit_operation_event(db, chat, actor, "release", reason)
    return OperationResult(
        chat=chat,
        event=event,
        before_chat=before,
        notification_target_role=ROLE_JEFE_OPERATIVO,
    )


def transferir_chat(
    db: Session,
    *,
    session_id: int,
    actor,
    destination: str,
    destination_user_id: str | None = None,
    reason: str | None = None,
) -> OperationResult:
    chat = lock_chat(db, session_id)
    if (
        destination in {"gestor", "gestor_cobranza"}
        and normalize_role(chat.assigned_role) == ROLE_GESTOR_COBRANZA
        and normalize_username(chat.assigned_user_id) == normalize_username(destination_user_id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya asignado a ese gestor")
    _ensure_can_transfer(chat, actor, destination, db)

    destination = str(destination or "").strip().lower()
    before = _snapshot(chat)
    previous_role = chat.assigned_role
    now = utcnow_naive()
    target_user = _validate_destination_user(
        db,
        actor=actor,
        destination=destination,
        destination_user_id=destination_user_id,
    )
    target_role = None

    chat.returned_from_role = previous_role
    chat.assigned_at = now
    chat.locked_until = None
    chat.transfer_pending = False
    chat.updated_at = now

    if destination in {"assistant", "assistant_active"}:
        chat.owner_type = OWNER_ASSISTANT
        chat.assigned_user_id = None
        chat.assigned_role = None
        chat.status_operativo = STATUS_ASSISTANT_ACTIVE
        chat.assigned_at = None
        chat.transfer_pending = False
        chat.transferred_by_user_id = None
        chat.transfer_reason = None
        chat.transfer_created_at = None
    elif destination == "cola_general":
        chat.owner_type = None
        chat.assigned_user_id = None
        chat.assigned_role = None
        chat.status_operativo = STATUS_UNASSIGNED
        chat.assigned_at = None
        target_role = ROLE_JEFE_OPERATIVO
        chat.transfer_pending = False
    elif destination in {"gestor", "gestor_cobranza"}:
        target_role = ROLE_GESTOR_COBRANZA
        chat.owner_type = OWNER_USER
        chat.assigned_user_id = target_user
        chat.assigned_role = target_role
        chat.status_operativo = STATUS_ASSIGNED_GESTOR
        chat.transfer_pending = False
        chat.transferred_by_user_id = None
        chat.transfer_reason = None
        chat.transfer_created_at = None
    elif destination in {"soporte", "soporte_tecnico"}:
        target_role = ROLE_SOPORTE_TECNICO
        chat.owner_type = OWNER_USER
        if normalize_role(chat.assigned_role) == ROLE_GESTOR_COBRANZA and chat.assigned_user_id:
            chat.previous_owner_user_id = chat.assigned_user_id
            chat.previous_owner_role = chat.assigned_role
        elif chat.previous_owner_user_id:
            chat.previous_owner_user_id = chat.previous_owner_user_id
            chat.previous_owner_role = chat.previous_owner_role
        else:
            chat.previous_owner_user_id = None
            chat.previous_owner_role = None
        chat.transferred_by_user_id = getattr(actor, "username", None)
        chat.transfer_reason = reason
        chat.transfer_created_at = now
        chat.assigned_user_id = target_user
        chat.assigned_role = target_role
        chat.status_operativo = STATUS_ASSIGNED_SOPORTE
        chat.transfer_pending = not bool(target_user)
        ensure_technical_log(
            db,
            chat=chat,
            detected_by="manual_transfer",
            keyword=None,
            description=reason,
            opened_by=getattr(actor, "username", None),
        )
    elif destination == "jefe_operativo":
        target_role = ROLE_JEFE_OPERATIVO
        chat.owner_type = OWNER_USER
        chat.assigned_user_id = target_user
        chat.assigned_role = target_role
        chat.status_operativo = STATUS_ESCALATED
        chat.priority = "high"
        chat.transfer_pending = not bool(target_user)
        chat.transferred_by_user_id = getattr(actor, "username", None)
        chat.transfer_reason = reason
        chat.transfer_created_at = now
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Destino invalido")

    _audit_transfer(db, chat=chat, action="transfer", actor=actor, before=before, reason=reason)
    event = _emit_operation_event(db, chat, actor, "transfer", reason)
    return OperationResult(
        chat=chat,
        event=event,
        before_chat=before,
        notification_target_user=target_user,
        notification_target_role=target_role,
    )

def send_to_assistant(
    db: Session,
    *,
    session_id: int,
    actor,
    reason: str | None = None,
) -> OperationResult:
    return transferir_chat(
        db,
        session_id=session_id,
        actor=actor,
        destination="assistant",
        reason=reason,
    )

def devolver_a_gestor(
    db: Session,
    *,
    session_id: int,
    actor,
    destination_user_id: str | None = None,
    reason: str | None = None,
) -> OperationResult:
    return transferir_chat(
        db,
        session_id=session_id,
        actor=actor,
        destination="gestor_cobranza",
        destination_user_id=destination_user_id,
        reason=reason,
    )


def devolver_a_soporte(
    db: Session,
    *,
    session_id: int,
    actor,
    destination_user_id: str | None = None,
    reason: str | None = None,
) -> OperationResult:
    return transferir_chat(
        db,
        session_id=session_id,
        actor=actor,
        destination="soporte_tecnico",
        destination_user_id=destination_user_id,
        reason=reason,
    )


def assign_chat_to_manager(
    db: Session,
    *,
    session_id: int,
    actor,
    manager_username: str,
    reason: str | None = None,
) -> OperationResult:
    if not has_permission(actor, "chat:assign_manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    chat = lock_chat(db, session_id)
    if not can_assign_manager_chat(chat, actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    if chat.status_operativo == STATUS_CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "La conversacion esta cerrada")

    if chat.status_operativo == STATUS_ASSIGNED_SOPORTE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La conversacion esta en soporte; cierra la incidencia antes de reasignar al gestor",
        )

    manager = get_active_staff_member(
        db,
        username=manager_username,
        empresa_id=_empresa_id_for_actor(actor),
        expected_role=ROLE_GESTOR_COBRANZA,
    )
    normalized_username = normalize_username(manager.nombre_usuario)
    if not normalized_username:
        raise HTTPException(status.HTTP_409_CONFLICT, "El gestor no tiene username operativo valido")
    if (
        normalize_role(chat.assigned_role) == ROLE_GESTOR_COBRANZA
        and normalize_username(chat.assigned_user_id) == normalized_username
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "La conversacion ya esta asignada a ese gestor")

    assignment_reason = reason or f"Asignacion manual a {normalized_username}"
    return transferir_chat(
        db,
        session_id=session_id,
        actor=actor,
        destination="gestor_cobranza",
        destination_user_id=normalized_username,
        reason=assignment_reason,
    )
def reasignacion_masiva(
    db: Session,
    *,
    session_ids: Iterable[int],
    actor,
    destination: str,
    destination_user_id: str | None = None,
    reason: str | None = None,
) -> list[OperationResult]:
    if not has_permission(actor, "chat:bulk_reassign"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    results: list[OperationResult] = []

    for session_id in session_ids:
        try:
            result = transferir_chat(
                db,
                session_id=int(session_id),
                actor=actor,
                destination=destination,
                destination_user_id=destination_user_id,
                reason=reason,
            )
            results.append(result)
        except HTTPException:
            continue

    return results

def ensure_technical_log(
    db: Session,
    *,
    chat: ChatSessions,
    detected_by: str,
    keyword: str | None,
    description: str | None = None,
    opened_by: str | None = None,
) -> ChatTechnicalLog:
    existing = (
        db.query(ChatTechnicalLog)
        .filter(
            ChatTechnicalLog.session_id == chat.id,
            ChatTechnicalLog.status == "open",
        )
        .order_by(ChatTechnicalLog.id.desc())
        .first()
    )
    if existing:
        return existing

    log = ChatTechnicalLog(
        session_id=chat.id,
        phone=chat.phone,
        detected_by=detected_by,
        keyword=keyword,
        description=description,
        status="open",
        opened_by=opened_by,
        sla_due_at=utcnow_naive() + timedelta(minutes=DEFAULT_TECHNICAL_SLA_MINUTES),
        created_at=utcnow_naive(),
    )
    db.add(log)
    db.flush()
    return log


def mark_technical_signal(
    db: Session,
    *,
    chat: ChatSessions,
    text: str | None,
    detected_by: str,
    actor=None,
) -> ChatTechnicalLog | None:
    keyword = detect_technical_keyword(text)
    if not keyword:
        return None

    initialize_operational_defaults(chat)
    chat.transfer_pending = True
    if chat.priority != "high":
        chat.priority = "medium"
    if chat.owner_type in {None, OWNER_ASSISTANT}:
        chat.status_operativo = STATUS_ESCALATED
    chat.updated_at = utcnow_naive()

    log = ensure_technical_log(
        db,
        chat=chat,
        detected_by=detected_by,
        keyword=keyword,
        description=text,
        opened_by=getattr(actor, "username", None),
    )
    emit_domain_event(
        db,
        event_type="chat.technical_signal",
        aggregate_type="chat_session",
        aggregate_id=chat.id,
        actor=actor,
        payload={
            "session_id": chat.id,
            "phone": chat.phone,
            "keyword": keyword,
            "status_operativo": chat.status_operativo,
            "priority": chat.priority,
            "transfer_pending": bool(chat.transfer_pending),
        },
    )
    return log


def return_to_original_gestor(
    db: Session,
    *,
    session_id: int,
    actor,
    reason: str | None = None,
    fallback_destination: str = "jefe_operativo",
) -> OperationResult:
    chat = lock_chat(db, session_id)
    original_user = chat.previous_owner_user_id

    if original_user and is_manager_active(
        db,
        username=original_user,
        empresa_id=_empresa_id_for_actor(actor),
    ):
        return transferir_chat(
            db,
            session_id=session_id,
            actor=actor,
            destination="gestor_cobranza",
            destination_user_id=original_user,
            reason=reason,
        )

    fallback = "cola_general" if fallback_destination == "cola_general" else "jefe_operativo"
    return transferir_chat(
        db,
        session_id=session_id,
        actor=actor,
        destination=fallback,
        destination_user_id=None,
        reason=reason or "Gestor original no disponible",
    )


def reassign_inactive_manager_chats(
    db: Session,
    *,
    actor,
    fallback_destination: str | None = None,
    limit: int = 200,
) -> list[OperationResult]:
    if not has_permission(actor, "chat:assign_manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    empresa_id = _empresa_id_for_actor(actor)
    destination = get_default_inactive_manager_destination(
        fallback_destination or getattr(settings, "PANEL_INACTIVE_MANAGER_FALLBACK", None)
    )

    candidates = (
        db.query(
            ChatSessions.id,
            ChatSessions.assigned_user_id,
            ChatSessions.phone,
            ChatSessions.test_mode,
        )
        .filter(
            ChatSessions.assigned_role == ROLE_GESTOR_COBRANZA,
            ChatSessions.assigned_user_id.isnot(None),
            ChatSessions.status_operativo.in_(
                [STATUS_ASSIGNED_GESTOR, "waiting_customer", STATUS_ESCALATED]
            ),
            ChatSessions.status_operativo != STATUS_CLOSED,
        )
        .limit(max(1, min(int(limit or 1), 500)))
        .all()
    )
    if normalize_role(getattr(actor, "role", None)) != ROLE_ADMIN:
        candidates = [
            item
            for item in candidates
            if not bool(getattr(item, "test_mode", False))
            and not is_test_phone(getattr(item, "phone", None))
        ]

    results: list[OperationResult] = []
    for candidate in candidates:
        if is_manager_active(db, username=candidate.assigned_user_id, empresa_id=empresa_id):
            continue
        results.append(
            transferir_chat(
                db,
                session_id=int(candidate.id),
                actor=actor,
                destination=destination,
                reason=f"Gestor inactivo en SIGA: {normalize_username(candidate.assigned_user_id)}",
            )
        )
    return results


def close_support_ticket(
    db: Session,
    *,
    session_id: int,
    actor,
    resolution: str | None = None,
    return_action: str = "return_to_original_gestor",
    fallback_destination: str = "jefe_operativo",
) -> OperationResult:
    allowed_return_actions = {
        "return_to_original_gestor",
        "assistant_active",
        "cola_general",
        "jefe_operativo",
    }
    if return_action not in allowed_return_actions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Accion de cierre invalida")

    chat = lock_chat(db, session_id)
    if not can_close_support_chat(chat, actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    log = (
        db.query(ChatTechnicalLog)
        .filter(ChatTechnicalLog.session_id == chat.id, ChatTechnicalLog.status == "open")
        .order_by(ChatTechnicalLog.id.desc())
        .first()
    )
    if not log:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incidencia tecnica no encontrada")

    log.status = "closed"
    log.closed_by = getattr(actor, "username", None)
    log.closed_at = utcnow_naive()
    log.resolution = resolution
    log.return_action = return_action
    if resolution:
        log.description = f"{log.description or ''}\n\nCierre: {resolution}".strip()

    chat.transfer_pending = False
    chat.updated_at = utcnow_naive()
    emit_domain_event(
        db,
        event_type="chat.technical_closed",
        aggregate_type="chat_session",
        aggregate_id=chat.id,
        actor=actor,
        payload={"session_id": chat.id, "technical_log_id": log.id},
    )
    db.flush()

    if return_action == "assistant_active":
        return send_to_assistant(db, session_id=session_id, actor=actor, reason=resolution)

    if return_action == "cola_general":
        return transferir_chat(db, session_id=session_id, actor=actor, destination="cola_general", reason=resolution)

    if return_action == "jefe_operativo":
        return transferir_chat(db, session_id=session_id, actor=actor, destination="jefe_operativo", reason=resolution)

    return return_to_original_gestor(
        db,
        session_id=session_id,
        actor=actor,
        reason=resolution,
        fallback_destination=fallback_destination,
    )


def technical_ticket_metrics(db: Session) -> dict:
    now = utcnow_naive()
    open_logs = (
        db.query(ChatTechnicalLog)
        .filter(ChatTechnicalLog.status == "open")
        .all()
    )
    pending = len(open_logs)
    overdue = sum(1 for log in open_logs if log.sla_due_at and log.sla_due_at < now)
    oldest_minutes = 0
    if open_logs:
        oldest = min((log.created_at for log in open_logs if log.created_at), default=None)
        if oldest:
            oldest_minutes = int((now - oldest).total_seconds() // 60)

    return {
        "pending": pending,
        "overdue": overdue,
        "oldest_minutes": oldest_minutes,
    }


close_technical_incident = close_support_ticket
