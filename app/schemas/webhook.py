from pydantic import BaseModel
from typing import Optional

class WebhookRequest(BaseModel):
    phone: Optional[str] = None
    state: str
    text: Optional[str] = None
    button_id: Optional[str] = None
