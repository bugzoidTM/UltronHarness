"""Barramento de eventos persistentes e assinaturas WebSocket em memória."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.db import Database


def now() -> str:
    return datetime.now(UTC).isoformat()


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def emit(
        self, event_type: str, payload: dict[str, Any], task_id: str | None = None
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid4()),
            "type": event_type,
            "task_id": task_id,
            "payload": payload,
            "created_at": now(),
        }
        self.db.execute(
            "INSERT INTO events (id, task_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (event["id"], task_id, event_type, self.db.json(payload), event["created_at"]),
        )
        queues = set(self._subscribers)
        if task_id:
            queues.update(self._task_subscribers.get(task_id, set()))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def history(self, task_id: str | None = None, limit: int = 250) -> list[dict[str, Any]]:
        if task_id:
            rows = self.db.all(
                "SELECT * FROM events WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            )
        else:
            rows = self.db.all("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,))
        return [
            {
                "id": row["id"],
                "type": row["event_type"],
                "task_id": row["task_id"],
                "payload": self.db.parse_json(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def subscribe(self, task_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        if task_id:
            self._task_subscribers[task_id].add(queue)
        else:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]], task_id: str | None = None) -> None:
        if task_id:
            self._task_subscribers[task_id].discard(queue)
        else:
            self._subscribers.discard(queue)
