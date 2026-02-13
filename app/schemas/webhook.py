from pydantic import BaseModel
from typing import Optional
from app.core.states import ChatState




class WebhookRequest(BaseModel):
    phone: Optional[str] = None
    state: ChatState
    text: Optional[str] = None
    button_id: Optional[str] = None
