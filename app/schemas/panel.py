from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# =========================
# REQUEST
# =========================
class SendMessageRequest(BaseModel):
    session_id: int
    content: str = Field(min_length=1, max_length=1000)


# =========================
# RESPONSES
# =========================
class ConversationResponse(BaseModel):
    id: int
    phone: str
    name: Optional[str] = None
    last_message: Optional[str]
    last_message_at: Optional[datetime]
    unread_count: int = 0


class MessageResponse(BaseModel):
    id: int
    direction: str
    content: str
    created_at: datetime

    type: Optional[str] = None
    media_url: Optional[str] = None
    file_name: Optional[str] = None


class PaginatedMessagesResponse(BaseModel):
    data: List[MessageResponse]
    total: int
    has_more: bool