import logging
from typing import List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


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

    def _can_send(self, websocket: WebSocket, roles: set[str] | None) -> bool:
        if not roles:
            return True
        user = getattr(websocket.state, "user", None)
        return str(getattr(user, "role", "") or "") in roles

    async def send_to_all(
        self,
        message: dict,
        *,
        roles: set[str] | tuple[str, ...] | None = None,
    ):
        allowed_roles = set(roles) if roles else None
        dead_connections = []
        sent_count = 0

        for ws in self.active_connections:
            if not self._can_send(ws, allowed_roles):
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
            },
        )


manager = ConnectionManager()
