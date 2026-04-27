from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import ChatSessions, Colaboradores, Message
from app.db.session import SessionLocal
from app.services.chat_operations import utcnow_naive
from app.services.panel_staff import get_available_managers, normalize_username


INTERNAL_STAFF_SEEDS = [
    {
        "username": "COL-PANELGEST1",
        "nombre": "PANEL GESTOR UNO",
        "puesto": "GESTOR DE COBRANZA",
        "jefe_directo": "PANEL JEFE OPERATIVO",
    },
    {
        "username": "COL-PANELGEST2",
        "nombre": "PANEL GESTOR DOS",
        "puesto": "GESTOR DE COBRANZA",
        "jefe_directo": "PANEL JEFE OPERATIVO",
    },
    {
        "username": "COL-PANELSOP1",
        "nombre": "PANEL SOPORTE UNO",
        "puesto": "SOPORTE TECNICO",
        "jefe_directo": "PANEL JEFE OPERATIVO",
    },
    {
        "username": "COL-PANELJEFE1",
        "nombre": "PANEL JEFE OPERATIVO",
        "puesto": "JEFE OPERATIVO",
        "jefe_directo": "GERENCIA GENERAL",
    },
]


def ensure_internal_staff(db: Session) -> None:
    for item in INTERNAL_STAFF_SEEDS:
        username = normalize_username(item["username"])
        exists = (
            db.query(Colaboradores.id)
            .filter(
                Colaboradores.id_emp_col == 1,
                Colaboradores.nombre_usuario == username,
            )
            .first()
        )
        if exists:
            continue

        db.add(
            Colaboradores(
                id_emp_col=1,
                id_matriz_col=1,
                nombre=item["nombre"],
                apellido_p="PANEL",
                apellido_m="TEST",
                nombre_completo=item["nombre"],
                nombre_resumido=item["nombre"],
                correo=f"{username.lower()}@panel.local",
                puesto=item["puesto"],
                jefe_directo=item["jefe_directo"],
                tipo="EMPLEADO",
                tipo_usu=3,
                nombre_usuario=username,
                contrasena="seed-only",
                premisas="seed-only",
                estatus=1,
            )
        )


def ensure_chat(
    db: Session,
    *,
    phone: str,
    folio: str,
    status_operativo: str,
    owner_type: str | None,
    assigned_user_id: str | None,
    assigned_role: str | None,
    previous_owner_user_id: str | None = None,
    previous_owner_role: str | None = None,
    transferred_by_user_id: str | None = None,
    transfer_reason: str | None = None,
    transfer_pending: bool = False,
):
    existing = db.query(ChatSessions).filter(ChatSessions.phone == phone).first()
    if existing:
        return existing

    now = utcnow_naive()
    session = ChatSessions(
        phone=phone,
        state="panel_seed",
        previous_state="assistant_active",
        folio=folio,
        owner_type=owner_type,
        assigned_user_id=assigned_user_id,
        assigned_role=assigned_role,
        status_operativo=status_operativo,
        priority="normal" if status_operativo != "escalated" else "high",
        transfer_pending=transfer_pending,
        assigned_at=now if assigned_user_id else None,
        last_message="Seguimiento operativo",
        last_message_at=now,
        last_agent_message_at=now if assigned_user_id or owner_type == "assistant" else None,
        last_customer_message_at=now - timedelta(minutes=15),
        unread_count=1 if status_operativo in {"unassigned", "assigned_gestor", "assigned_soporte"} else 0,
        previous_owner_user_id=previous_owner_user_id,
        previous_owner_role=previous_owner_role,
        transferred_by_user_id=transferred_by_user_id,
        transfer_reason=transfer_reason,
        transfer_created_at=now if transferred_by_user_id else None,
        test_mode=False,
        updated_at=now,
    )
    db.add(session)
    db.flush()
    return session


def ensure_messages(db: Session, *, session: ChatSessions, outgoing_author: str | None = None) -> None:
    exists = db.query(Message.id).filter(Message.session_id == session.id).first()
    if exists:
        return

    now = utcnow_naive()
    history = [
        Message(
            session_id=session.id,
            phone=session.phone,
            direction="in",
            content="Hola, necesito revisar mi cuenta.",
            created_at=now - timedelta(minutes=25),
            type="text",
        ),
        Message(
            session_id=session.id,
            phone=session.phone,
            direction="agent" if outgoing_author else "out",
            content=(
                f"{outgoing_author}: ya estoy revisando tu caso."
                if outgoing_author
                else "Assistant: ya estoy revisando tu caso."
            ),
            created_at=now - timedelta(minutes=20),
            type="text",
        ),
        Message(
            session_id=session.id,
            phone=session.phone,
            direction="in",
            content="Quedo atento.",
            created_at=now - timedelta(minutes=15),
            type="text",
        ),
    ]
    db.add_all(history)


def seed_panel_operational_data() -> None:
    db = SessionLocal()
    try:
        ensure_internal_staff(db)
        db.flush()

        managers = get_available_managers(db, empresa_id=1)
        manager_one = managers[0].username if managers else "COL-PANELGEST1"
        manager_two = managers[1].username if len(managers) > 1 else manager_one
        support_user = "COL-PANELSOP1"

        definitions = [
            ("5214271900101", "PANEL-0001", "unassigned", None, None, None, None, None, None, None, False),
            ("5214271900102", "PANEL-0002", "unassigned", None, None, None, None, None, None, None, False),
            ("5214271900103", "PANEL-0003", "assigned_gestor", "user", manager_one, "gestor_cobranza", None, None, None, None, False),
            ("5214271900104", "PANEL-0004", "assigned_gestor", "user", manager_two, "gestor_cobranza", None, None, None, None, False),
            ("5214271900105", "PANEL-0005", "assigned_soporte", "user", support_user, "soporte_tecnico", manager_one, "gestor_cobranza", manager_one, "Falla tecnica reportada", True),
            ("5214271900106", "PANEL-0006", "waiting_customer", "user", manager_one, "gestor_cobranza", None, None, None, None, False),
            ("5214271900107", "PANEL-0007", "escalated", "user", None, "jefe_operativo", None, None, None, None, False),
            ("5214271900108", "PANEL-0008", "closed", "assistant", None, None, None, None, None, None, False),
        ]

        for item in definitions:
            session = ensure_chat(
                db,
                phone=item[0],
                folio=item[1],
                status_operativo=item[2],
                owner_type=item[3],
                assigned_user_id=item[4],
                assigned_role=item[5],
                previous_owner_user_id=item[6],
                previous_owner_role=item[7],
                transferred_by_user_id=item[8],
                transfer_reason=item[9],
                transfer_pending=item[10],
            )
            ensure_messages(db, session=session, outgoing_author=session.assigned_user_id)

        db.commit()
        print("Panel operational seed applied.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_panel_operational_data()
