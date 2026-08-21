"""Persistência transacional de continuações de tarefas aguardando aprovação."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ultron.db import Database


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ContinuationStore:
    def __init__(self, db: Database):
        self.db = db
        self.db.initialize()

    def save(self, task_id: str, approval_id: str, execution_id: str, revision: int, step_index: int, payload: dict[str, Any]) -> None:
        timestamp = utcnow()
        self.db.execute(
            "INSERT INTO task_continuations (task_id,approval_id,tool_execution_id,plan_revision,step_index,payload_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET approval_id=excluded.approval_id,tool_execution_id=excluded.tool_execution_id,plan_revision=excluded.plan_revision,step_index=excluded.step_index,payload_json=excluded.payload_json,status='waiting_approval',updated_at=excluded.updated_at",
            (task_id, approval_id, execution_id, revision, step_index, self.db.json(payload), "waiting_approval", timestamp, timestamp),
        )

    def load(self, task_id: str, approval_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM task_continuations WHERE task_id=? AND status='waiting_approval'"
        params: tuple[Any, ...] = (task_id,)
        if approval_id:
            sql += " AND approval_id=?"
            params = (task_id, approval_id)
        row = self.db.one(sql, params)
        if not row:
            return None
        row["payload"] = self.db.parse_json(row.pop("payload_json"), {})
        return row

    def mark_resuming(self, task_id: str) -> None:
        self.db.execute("UPDATE task_continuations SET status='resuming',updated_at=? WHERE task_id=?", (utcnow(), task_id))

    def delete(self, task_id: str) -> None:
        self.db.execute("DELETE FROM task_continuations WHERE task_id=?", (task_id,))

    def recoverable(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM task_continuations WHERE status='waiting_approval' ORDER BY updated_at")
        for row in rows:
            row["payload"] = self.db.parse_json(row.pop("payload_json"), {})
        return rows
