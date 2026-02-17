from pydantic import BaseModel
from typing import Optional


class WebhookRequest(BaseModel):
    phone: str
    text: str
    button_id: Optional[str] = None
    message_id: str
