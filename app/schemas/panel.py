# app/schemas/panel.py

from pydantic import BaseModel
from datetime import datetime


class ConversationResponse(BaseModel):
    phone: str
    state: str
    last_message: str | None
    last_message_at: datetime | None


class MessageResponse(BaseModel):
    id: int
    phone: str
    direction: str
    text: str | None
    created_at: datetime


class SendMessageRequest(BaseModel):
    phone: str
    text: str