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

async def send_reminder(db: Session, session: ChatSessions, reminder_type: str):

    if reminder_type == TYPE_1H:
        state = ChatState.RECORDATORIO_1H
    elif reminder_type == TYPE_2H:
        state = ChatState.RECORDATORIO_2H
    elif reminder_type == TYPE_24H:
        state = ChatState.RECORDATORIO_24H
    else:
        return

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

    await send_whatsapp_message(session.phone, text, buttons)


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
        .filter(Reminder.type.in_([TYPE_1H, TYPE_2H, TYPE_24H]))
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

            await send_reminder(
                db=db,
                session=session,
                reminder_type=r.type
            )

            # commit después de enviar
            db.commit()

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
