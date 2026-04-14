from dataclasses import dataclass
from typing import Optional, Any

from app.core.states.states import ChatState


@dataclass
class ConversationContext:
    """
    Contiene toda la información relevante de la conversación
    en un solo objeto.

    NO debe contener lógica de negocio.
    """

    # Estado actual
    state: ChatState

    # Estado anterior (para reanudación)
    previous_state: Optional[str]

    # Entrada del usuario
    text: str

    # Intent detectado
    intent: Optional[str]

    # Datos de sesión
    phone: Optional[str]
    folio: Optional[str]

    # Datos externos (SIGA)
    venta: Optional[Any] = None

    session: Optional[Any] = None
    db: Optional[Any] = None

    # --------------------------------------
    # Helpers útiles
    # --------------------------------------

    def has_folio(self) -> bool:
        return self.folio is not None

    def is_verification_flow(self) -> bool:
        """
        Indica si el usuario ya está en flujo de verificación.
        """
        return self.has_folio()

    def is_out_of_flow(self) -> bool:
        return self.intent in ["other", "ambiguous"]

    def is_doubt(self) -> bool:
        return self.intent == "doubt"

    def is_human_request(self) -> bool:
        return self.intent == "human"

    def should_resume(self) -> bool:
        return self.intent == "affirmative"

    def previous_as_state(self) -> Optional[ChatState]:
        if self.previous_state:
            return ChatState(self.previous_state)
        return None