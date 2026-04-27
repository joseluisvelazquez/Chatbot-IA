from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Dict, Set
from uuid import uuid4

from fastapi import WebSocket

from app.security.rbac import ROLE_ADMIN, can_view_chat, normalize_role


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


@dataclass
class ConnectionContext:
    websocket: WebSocket
    username: str
    role: str
    raw_user: object
    connected_at: datetime = field(default_factory=datetime.utcnow)
    channels: set[str] = field(default_factory=set)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, ConnectionContext] = {}
        self.channels: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._max_tabs_per_user = 3

    def _channels_for_user(self, user) -> set[str]:
        role = normalize_role(getattr(user, "role", None))
        username = str(getattr(user, "username", "") or "").strip()

        channels = {
            "global",
            f"role:{role}",
        }

        if username:
            channels.add(f"user:{username}")

        if role == ROLE_ADMIN:
            channels.add("admin")

        return channels

    def _prepare_message(self, message: dict) -> dict:
        return {
            "event_id": message.get("event_id") or uuid4().hex,
            "sent_at": message.get("sent_at") or utcnow_iso(),
            **message,
        }

    async def connect(self, websocket: WebSocket, user) -> None:
        role = normalize_role(getattr(user, "role", None))
        username = str(getattr(user, "username", "") or "").strip()
        channels = self._channels_for_user(user)

        async with self._lock:
            if username:
                same_user = [
                    ctx
                    for ctx in self.active_connections.values()
                    if ctx.username == username
                ]

                if len(same_user) >= self._max_tabs_per_user:
                    same_user.sort(key=lambda item: item.connected_at)

                    excess = len(same_user) - self._max_tabs_per_user + 1

                    for ctx in same_user[:excess]:
                        try:
                            await ctx.websocket.close(code=1000)
                        except Exception:
                            pass
                        await self.disconnect(ctx.websocket)

            context = ConnectionContext(
                websocket=websocket,
                username=username,
                role=role,
                raw_user=user,
                channels=channels,
            )

            self.active_connections[websocket] = context

            for channel in channels:
                self.channels.setdefault(channel, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            context = self.active_connections.pop(websocket, None)

            if not context:
                return

            for channel in context.channels:
                sockets = self.channels.get(channel)

                if not sockets:
                    continue

                sockets.discard(websocket)

                if not sockets:
                    self.channels.pop(channel, None)

    async def _send_many(self, sockets: set[WebSocket], message: dict) -> None:
        if not sockets:
            return

        payload = self._prepare_message(message)

        async def safe_send(ws: WebSocket):
            try:
                await ws.send_json(payload)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(
            *(safe_send(ws) for ws in list(sockets)),
            return_exceptions=False,
        )

        dead_connections = [ws for ws in results if ws is not None]

        for websocket in dead_connections:
            await self.disconnect(websocket)

    async def send_to_all(self, message: dict) -> None:
        await self._send_many(set(self.active_connections.keys()), message)

    async def send_to_channel(self, channel: str, message: dict) -> None:
        await self._send_many(set(self.channels.get(channel, set())), message)

    async def send_to_user(self, username: str | None, message: dict) -> None:
        if not username:
            return

        await self.send_to_channel(f"user:{username}", message)

    async def send_to_role(self, role: str | None, message: dict) -> None:
        if not role:
            return

        await self.send_to_channel(
            f"role:{normalize_role(role)}",
            message,
        )

    async def send_to_admins(self, message: dict) -> None:
        await self.send_to_channel("admin", message)

    async def send_to_chat_watchers(self, chat, message: dict) -> None:
        sockets = {
            websocket
            for websocket, context in self.active_connections.items()
            if can_view_chat(chat, context.raw_user)
        }

        await self._send_many(sockets, message)

    async def send_to_chat_watchers_personalized(
        self,
        chat,
        build_message,
    ) -> None:
        dead_connections = []

        for websocket, context in list(self.active_connections.items()):
            if not can_view_chat(chat, context.raw_user):
                continue

            try:
                payload = self._prepare_message(
                    build_message(context.raw_user)
                )
                await websocket.send_json(payload)
            except Exception:
                dead_connections.append(websocket)

        for websocket in dead_connections:
            await self.disconnect(websocket)

    async def send_chat_transition(
        self,
        *,
        before_chat: dict | None,
        after_chat,
        build_message,
        build_removal_message,
    ) -> None:
        dead_connections = []
        before_namespace = None

        if before_chat is not None:
            before_namespace = SimpleNamespace(**before_chat)

        for websocket, context in list(self.active_connections.items()):
            raw_user = context.raw_user

            could_view_before = bool(
                before_namespace
                and can_view_chat(before_namespace, raw_user)
            )

            can_view_after = bool(
                after_chat
                and can_view_chat(after_chat, raw_user)
            )

            if not could_view_before and not can_view_after:
                continue

            try:
                if can_view_after:
                    payload = self._prepare_message(
                        build_message(raw_user)
                    )
                else:
                    payload = self._prepare_message(
                        build_removal_message(raw_user)
                    )

                await websocket.send_json(payload)

            except Exception:
                dead_connections.append(websocket)

        for websocket in dead_connections:
            await self.disconnect(websocket)

    async def send_heartbeat(self) -> None:
        await self.send_to_all({"type": "heartbeat"})

    def stats(self) -> dict:
        role_counts: dict[str, int] = {}

        for context in self.active_connections.values():
            role_counts[context.role] = (
                role_counts.get(context.role, 0) + 1
            )

        return {
            "connections": len(self.active_connections),
            "channels": len(self.channels),
            "roles": role_counts,
        }


manager = ConnectionManager()