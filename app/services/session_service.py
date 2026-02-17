from sqlalchemy.orm import Session
from app.db.models import ChatSession
from app.core.states import ChatState

# Estas funciones se encargan de manejar la sesión de chat, que es lo que permite mantener el contexto de la conversación con cada usuario. Se usan para crear o recuperar la sesión al recibir un mensaje, y para actualizarla después de procesar el mensaje y decidir la respuesta y el siguiente estado.
def get_or_create_session(db: Session, phone: str, folio: str | None = None):
    session = (
        db.query(ChatSession)
        .filter_by(phone=phone)
        .with_for_update()   # 🔒 lock fila
        .first()
    )

    if not session:
        session = ChatSession(
            phone=phone,
            folio=folio,
            state=ChatState.ESPERA.value,
        )
        db.add(session)
        db.flush()  # 👈 NO commit

    return session

# Esta función actualiza la sesión con el nuevo estado, el último mensaje, el estado previo (si corresponde) y el ID del mensaje (para control de duplicados). Se llama dentro de la transacción en el webhook, después de procesar el mensaje y decidir la respuesta y el siguiente estado.
def update_session(
    session: ChatSession,
    state: str,
    last_message: str,
    previous_state: str | None = None,
    message_id: str | None = None,
):
    session.state = state
    session.last_message = last_message

    if previous_state is not None:
        session.previous_state = previous_state

    if message_id is not None:
        session.last_message_id = message_id

    return session
