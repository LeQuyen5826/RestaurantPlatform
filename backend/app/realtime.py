"""WebSocket theo phòng (room). Phát từ code đồng bộ (threadpool) bằng run_coroutine_threadsafe."""
import asyncio
from collections import defaultdict

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, rooms: list[str]) -> None:
        await ws.accept()
        for r in rooms:
            self.rooms[r].add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        for members in self.rooms.values():
            members.discard(ws)

    async def _send(self, room: str, data: dict) -> None:
        dead = []
        for ws in list(self.rooms.get(room, ())):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def publish(self, rooms: str | list[str], data: dict) -> None:
        if not (self.loop and self.loop.is_running()):
            return
        for room in [rooms] if isinstance(rooms, str) else rooms:
            asyncio.run_coroutine_threadsafe(self._send(room, data), self.loop)


hub = Hub()
