from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.db.models import Reminder, ChatSessions
from app.utils.timezone import mexico_now_naive

TYPE_1H = "INACTIVITY_1H"
TYPE_2H = "INACTIVITY_2H"
TYPE_24H = "INACTIVITY_24H"
TYPE_TIMEOUT = "INACTIVITY_TIMEOUT"

def utcnow_naive() -> datetime:
    return mexico_now_naive()


def cancel_pending_inactivity_reminders(db: Session, phone: str) -> None:
    now = utcnow_naive()
    (
        db.query(Reminder)
        .filter(Reminder.phone == phone)
        .filter(Reminder.type.in_([TYPE_1H, TYPE_2H, TYPE_24H, TYPE_TIMEOUT]))
        .filter(Reminder.sent_at.is_(None))
        .filter(Reminder.cancelled_at.is_(None))
        .update({Reminder.cancelled_at: now}, synchronize_session=False)
    )


def create_inactivity_reminders(db: Session, session: ChatSessions) -> None:
    """
    Regla: scheduled_at se calcula desde la actividad real.
    Para pruebas, puedes cambiar hours->minutes aquí sin tocar el job.
    """
    now = utcnow_naive()
    base = session.last_message_at or now

    db.add(
        Reminder(
            session_id=session.id,
            phone=session.phone,
            type=TYPE_1H,
            scheduled_at=base + timedelta(hours=1),
            created_last_message_id=session.last_message_id,
        )
    )
    db.add(
        Reminder(
            session_id=session.id,
            phone=session.phone,
            type=TYPE_2H,
            scheduled_at=base + timedelta(hours=2),
            created_last_message_id=session.last_message_id,
        )
    )
    db.add(
        Reminder(
            session_id=session.id,
            phone=session.phone,
            type=TYPE_24H,
            scheduled_at=base + timedelta(hours=23, minutes=59),
            created_last_message_id=session.last_message_id,
        )
    )
    db.add(
        Reminder(
            session_id=session.id,
            phone=session.phone,
            type=TYPE_TIMEOUT,
            scheduled_at=base + timedelta(hours=48),
            created_last_message_id=session.last_message_id,
        )
    )


from app.core.states.state_types import is_terminal_state, is_persistent_state
from app.core.states.states import ChatState

def upsert_inactivity_reminders(db: Session, session: ChatSessions) -> None:
    cancel_pending_inactivity_reminders(db, session.phone)
    try:
        current_state = ChatState(session.state)
        if is_persistent_state(current_state) and not is_terminal_state(current_state):
            create_inactivity_reminders(db, session)
    except ValueError:
        pass  # In case state is not a valid ChatState
