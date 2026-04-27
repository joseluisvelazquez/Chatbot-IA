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
    no_cuenta: str | None = None
    folio: str | None = None
    owner_type: str | None = None
    assigned_user_id: str | None = None
    assigned_role: str | None = None
    status_operativo: str | None = None
    priority: str | None = None
    transfer_pending: bool = False
    locked_until: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    last_agent_message_at: Optional[datetime] = None
    last_customer_message_at: Optional[datetime] = None
    returned_from_role: str | None = None
    transferred_by_user_id: str | None = None
    previous_owner_user_id: str | None = None
    previous_owner_role: str | None = None
    transfer_reason: str | None = None
    transfer_created_at: Optional[datetime] = None
    test_mode: bool = False
    requires_human: bool = False
    can_reply: bool = False
    can_take: bool = False
    can_transfer: bool = False
    can_assign_manager: bool = False
    can_transfer_to_support: bool = False
    can_return_to_gestor: bool = False
    can_return_to_assistant: bool = False
    can_escalate: bool = False
    can_release: bool = False
    can_close_support: bool = False
    has_pending_action: bool = False


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


class TakeChatRequest(BaseModel):
    target_role: str | None = None


class TransferChatRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=40)
    destination_user_id: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class OperationReasonRequest(BaseModel):
    destination_user_id: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class CloseSupportTicketRequest(BaseModel):
    resolution: str | None = Field(default=None, max_length=1000)
    return_action: str = Field(default="return_to_original_gestor", max_length=40)
    fallback_destination: str = Field(default="jefe_operativo", max_length=40)


class BulkReassignRequest(BaseModel):
    session_ids: list[int] = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=2, max_length=40)
    destination_user_id: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool
    description: str | None = Field(default=None, max_length=500)


class AvailableManagerResponse(BaseModel):
    username: str
    nombre: str
    jefe_directo: str | None = None
    puesto: str | None = None
    current_load: int = 0
    is_online: bool = False
    duplicate_rows: int = 1


class AssignManagerRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=45)
    reason: str | None = Field(default=None, max_length=500)
