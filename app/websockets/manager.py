import logging
from typing import List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _message_session_id(message: dict) -> int | None:
    raw_session_id = message.get("session_id")
    if raw_session_id is None and isinstance(message.get("payload"), dict):
        raw_session_id = message["payload"].get("session_id")
    if raw_session_id is None:
        return None
    try:
        return int(raw_session_id)
    except (TypeError, ValueError):
        return None


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    def connect(self, websocket: WebSocket):
        self.active_connections.append(websocket)
        logger.info("websocket_connected", extra={"connections": len(self.active_connections)})

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("websocket_disconnected", extra={"connections": len(self.active_connections)})

    def _can_send(
        self,
        websocket: WebSocket,
        roles: set[str] | None,
        session_id: int | None,
    ) -> bool:
        user = getattr(websocket.state, "user", None)
        if roles and str(getattr(user, "role", "") or "") not in roles:
            return False

        allowed_session_ids = getattr(websocket.state, "allowed_session_ids", None)
        if allowed_session_ids is None or session_id is None:
            return True

        return session_id in allowed_session_ids

    async def send_to_all(
        self,
        message: dict,
        *,
        roles: set[str] | tuple[str, ...] | None = None,
    ):
        allowed_roles = set(roles) if roles else None
        session_id = _message_session_id(message)
        dead_connections = []
        sent_count = 0

        for ws in self.active_connections:
            if not self._can_send(ws, allowed_roles, session_id):
                continue
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception as exc:
                logger.warning(
                    "websocket_send_failed",
                    extra={
                        "event_type": message.get("type"),
                        "error_type": exc.__class__.__name__,
                    },
                )
                dead_connections.append(ws)

        for ws in dead_connections:
            self.disconnect(ws)

        logger.info(
            "websocket_broadcast_done",
            extra={
                "event_type": message.get("type"),
                "sent_count": sent_count,
                "roles": sorted(allowed_roles) if allowed_roles else None,
                "session_scoped": session_id is not None,
            },
        )


manager = ConnectionManager()
