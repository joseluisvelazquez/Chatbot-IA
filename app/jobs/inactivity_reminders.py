import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import Reminder, ChatSessions
from app.services.reminder_service import TYPE_1H, TYPE_2H
from app.adapters.whatsapp_client import send_whatsapp_message

# 🔒 Opcional: limita a un número para pruebas
TEST_PHONE_ONLY = "5214271227177"  # ejemplo: "5214271227177"

REMINDER_TEXT = {
    TYPE_1H: "👋 ¿Sigues ahí? Podemos continuar con tu verificación cuando gustes.",
    TYPE_2H: "⏰ Último recordatorio por ahora. Si quieres continuar, aquí estoy.",
}

BUTTONS = [{"id": "REANUDACION", "label": "▶️ Continuar"}]


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _send_due_reminders(db: Session) -> None:
    now = utcnow_naive()

    due = (
        db.query(Reminder)
        .filter(Reminder.scheduled_at <= now)
        .filter(Reminder.sent_at.is_(None))
        .filter(Reminder.cancelled_at.is_(None))
        .filter(Reminder.type.in_([TYPE_1H, TYPE_2H]))
        .order_by(Reminder.scheduled_at.asc())
        .limit(200)
        .all()
    )

    for r in due:
        if TEST_PHONE_ONLY and r.phone != TEST_PHONE_ONLY:
            continue

        session = db.query(ChatSessions).filter(ChatSessions.id == r.session_id).first()
        if not session:
            r.cancelled_at = now
            continue

        # Fix 4: si hubo actividad después de programar -> cancelar
        if r.created_last_message_id and session.last_message_id != r.created_last_message_id:
            r.cancelled_at = now
            continue

        # Sanidad: si no tenemos last_message_at, no dejamos zombies
        if session.last_message_at is None:
            r.cancelled_at = now
            continue

        # ✅ PRUEBAS: 100s para "1H"
        elapsed_seconds = (now - session.last_message_at).total_seconds()
        if r.type == TYPE_1H and elapsed_seconds < 2:
            continue

        # (Si quieres, para TYPE_2H haces 200s o lo que uses en pruebas)
        # if r.type == TYPE_2H and elapsed_seconds < 200:
        #     continue

        # ---------------- Fix 6: claim atómico (Patrón A) ----------------
        claimed = (
            db.query(Reminder)
            .filter(
                Reminder.id == r.id,
                Reminder.sent_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
            .update({Reminder.sent_at: now}, synchronize_session=False)
        )
        db.commit()

        if claimed != 1:
            # otro proceso lo tomó
            continue

        try:
            await send_whatsapp_message(r.phone, REMINDER_TEXT[r.type], BUTTONS)
        except Exception:
            # Unclaim para permitir reintento
            db.query(Reminder).filter(Reminder.id == r.id).update(
                {Reminder.sent_at: None}, synchronize_session=False
            )
            db.commit()
            raise

    db.commit()


def run_inactivity_reminders_job() -> None:
    db = SessionLocal()
    try:
        asyncio.run(_send_due_reminders(db))
    finally:
        db.close()