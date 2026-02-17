from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    __table_args__ = (UniqueConstraint("phone", name="uq_chat_phone"),)

    id = Column(Integer, primary_key=True, index=True)

    # Identificación del usuario
    phone = Column(String(20), nullable=False, index=True)
    folio = Column(String(50), nullable=True, index=True)

    # Estados del bot
    state = Column(String(50), nullable=False)
    previous_state = Column(String(50), nullable=True)

    # Último mensaje recibido
    last_message = Column(Text, nullable=True)

    # Control de concurrencia
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # id del último mensaje procesado
    last_message_id = Column(String(100), nullable=True)
