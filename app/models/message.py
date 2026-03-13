from pydantic import BaseModel
from app.core.states import ChatState
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from datetime import datetime
from app.db.base import Base


class IncomingMessage(BaseModel):
    state: ChatState
    text: str | None = None
    button_id: str | None = None


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    phone = Column(String(20), index=True)

    direction = Column(
        Enum("in", "out", "agent", name="message_direction"),
        nullable=False
    )

    content = Column(Text)

    message_id = Column(String(120), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)