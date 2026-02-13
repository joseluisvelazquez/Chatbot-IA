from pydantic import BaseModel
from app.core.states import ChatState


class IncomingMessage(BaseModel):
    state: ChatState
    text: str | None = None
    button_id: str | None = None
