from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.db.models import Reminder, ChatSessions

TYPE_1H = "INACTIVITY_1H"
TYPE_2H = "INACTIVITY_2H"


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cancel_pending_inactivity_reminders(db: Session, session_id: int) -> None:
    now = utcnow_naive()
    (
        db.query(Reminder)
        .filter(Reminder.session_id == session_id)
        .filter(Reminder.type.in_([TYPE_1H, TYPE_2H]))
        .filter(Reminder.sent_at.is_(None))
        .filter(Reminder.cancelled_at.is_(None))
        .update({Reminder.cancelled_at: now}, synchronize_session=False)
    )


def create_inactivity_reminders(db: Session, session: ChatSessions) -> None:
    """
    Regla: scheduled_at se calcula desde la actividad real.
    Para pruebas, puedes cambiar hours->seconds aquí sin tocar el job.
    """
    now = utcnow_naive()
    base = session.last_message_at or now

    db.add(
        Reminder(
            session_id=session.id,
            phone=session.phone,
            type=TYPE_1H,
            scheduled_at=base + timedelta(minutes=5),  # para pruebas, 5 min
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


def upsert_inactivity_reminders(db: Session, session: ChatSessions) -> None:
    cancel_pending_inactivity_reminders(db, session.id)
    create_inactivity_reminders(db, session)