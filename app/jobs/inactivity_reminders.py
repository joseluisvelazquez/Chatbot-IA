import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import Reminder, ChatSessions
from app.services.reminder_service import TYPE_1H, TYPE_2H, TYPE_24H
from app.adapters.whatsapp_client import send_whatsapp_message
from app.core.flow.flow import FLOW
from app.core.states.states import ChatState
from app.utils.timezone import mexico_now_naive


# 🔒 Opcional: limitar a un número durante pruebas
TEST_PHONE_ONLY = []


def utcnow_naive() -> datetime:
    return mexico_now_naive()


# ------------------------------------------------------------
# ENVÍO DE RECORDATORIO
# ------------------------------------------------------------

from app.core.states.state_types import is_persistent_state
from app.core.states.state_renderer import render_state
from app.services.message_service import save_message
from app.services.message_metadata import build_outgoing_interactive_metadata

async def send_reminder(db: Session, session: ChatSessions, reminder_type: str):

    if reminder_type == TYPE_1H:
        state = ChatState.RECORDATORIO_1H
    elif reminder_type == TYPE_2H:
        state = ChatState.RECORDATORIO_2H
    elif reminder_type == TYPE_24H:
        state = ChatState.RECORDATORIO_24H
    elif reminder_type == "INACTIVITY_TIMEOUT":
        # 🕒 Solo cambiamos el estado, no enviamos mensaje (fuera de ventana de 24h)
        session.previous_state = session.state
        session.state = ChatState.LLAMADA.value
        
        # Notificar al panel del cambio a LLAMADA
        try:
            # 🔔 Notificar a asesores por WhatsApp
            from app.services.notification_service import notify_advisors_new_case
            from app.services.verification_service import VerificationService
            service = VerificationService(db)
            no_cuenta_val = service.resolve_no_cuenta_from_folio(str(session.folio), 1) if session.folio else None # asumimos empresa 1
            
            await notify_advisors_new_case(session, "El cliente no ha respondido los mensajes y se requiere contacto manual.", no_cuenta=no_cuenta_val)
        except Exception:
            pass
        return True
    else:
        return False

    node = FLOW[state]
    text = node["text"]
    buttons = node["buttons"]

    try:
        current_state_enum = ChatState(session.state)
        if is_persistent_state(current_state_enum):
            session.previous_state = session.state
    except ValueError:
        pass

    session.state = state.value

    # Guardamos el mensaje en la BD para que sea visible en el panel
    outgoing_metadata = build_outgoing_interactive_metadata(text, buttons) if buttons else None
    bot_msg = save_message(
        db=db,
        session_id=session.id,
        phone=session.phone,
        direction="out",
        content=text,
        type="text",
        extra_json=outgoing_metadata,
    )

    await send_whatsapp_message(session.phone, text, buttons)
    return bot_msg


async def broadcast_reminder_update(db: Session, session: ChatSessions, bot_msg=None) -> None:
    try:
        from app.services.verification_panel_service import build_verification_snapshot
        from app.services.ws_events import build_verification_updated_event, build_new_message_event
        from app.websockets.manager import manager

        snapshot = build_verification_snapshot(db, session)
        event = build_verification_updated_event(snapshot, source="reminder") if snapshot else None
        if event:
            await manager.send_to_all(event)
            
        if bot_msg:
            msg_event = build_new_message_event(session, bot_msg)
            if msg_event:
                await manager.send_to_all(msg_event)
    except Exception:
        pass


# ------------------------------------------------------------
# JOB PRINCIPAL
# ------------------------------------------------------------

async def _send_due_reminders(db: Session) -> None:

    now = utcnow_naive()

    due = (
        db.query(Reminder)
        .filter(Reminder.scheduled_at <= now)
        .filter(Reminder.sent_at.is_(None))
        .filter(Reminder.cancelled_at.is_(None))
        .filter(Reminder.type.in_([TYPE_1H, TYPE_2H, TYPE_24H, "INACTIVITY_TIMEOUT"]))
        .order_by(Reminder.scheduled_at.asc())
        .limit(200)
        .all()
    )

    for r in due:

        # filtro para pruebas
        if TEST_PHONE_ONLY and r.phone not in TEST_PHONE_ONLY:
            continue

        session = (
            db.query(ChatSessions)
            .filter(ChatSessions.id == r.session_id)
            .with_for_update()
            .first()
        )

        if not session:
            r.cancelled_at = now
            continue

        # si el usuario respondió después de programar reminder
        if r.created_last_message_id and session.last_message_id != r.created_last_message_id:
            r.cancelled_at = now
            continue

        # claim atómico
        claimed = (
            db.query(Reminder)
            .filter(
                Reminder.id == r.id,
                Reminder.sent_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
            .update({Reminder.sent_at: now}, synchronize_session=False)
        )

        if claimed != 1:
            continue

        try:

            bot_msg = await send_reminder(
                db=db,
                session=session,
                reminder_type=r.type
            )

            # commit después de enviar
            db.commit()
            if bot_msg:
                # bot_msg puede ser True si fue TIMEOUT, en ese caso enviamos None
                await broadcast_reminder_update(db, session, bot_msg if hasattr(bot_msg, 'id') else None)

        except Exception:
            db.rollback()

            db.query(Reminder).filter(Reminder.id == r.id).update(
                {Reminder.sent_at: None},
                synchronize_session=False
            )

            db.commit()
            raise


# ------------------------------------------------------------
# ENTRYPOINT DEL SCHEDULER
# ------------------------------------------------------------

def run_inactivity_reminders_job() -> None:

    db = SessionLocal()

    try:
        asyncio.run(_send_due_reminders(db))

    finally:
        db.close()
