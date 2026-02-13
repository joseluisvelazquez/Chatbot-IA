from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from app.db.session import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=False)
    folio = Column(String(50))
    state = Column(String(50), nullable=False)
    previous_state = Column(String(50), nullable=True)
    last_message = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)
