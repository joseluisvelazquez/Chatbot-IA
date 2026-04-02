from fastapi import WebSocket
from typing import List

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    def connect(self, websocket: WebSocket):
        self.active_connections.append(websocket)
        print(f"🟢 WS conectado. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"🔴 WS desconectado. Total: {len(self.active_connections)}")

    async def send_to_all(self, message: dict):
        print(f"📡 Broadcasting: {message}")

        dead_connections = []

        for ws in self.active_connections:
            try:
                await ws.send_json(message)  # 🔥 IMPORTANTE: await
            except Exception as e:
                print("❌ Error enviando WS:", e)
                dead_connections.append(ws)

        # limpiar conexiones muertas
        for ws in dead_connections:
            self.disconnect(ws)


manager = ConnectionManager()