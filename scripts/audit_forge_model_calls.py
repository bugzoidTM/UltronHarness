from __future__ import annotations

import sqlite3
from pathlib import Path

DATABASE = Path("data/ultron.db")


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT t.id AS task_id, t.title, t.workspace, t.status,
               mc.model, mc.purpose, mc.latency_ms, mc.prompt_tokens,
               mc.output_tokens, mc.finish_reason, mc.created_at
          FROM tasks t
          LEFT JOIN model_calls mc ON mc.task_id = t.id AND mc.purpose = 'planning'
         WHERE t.workspace LIKE 'forge_%'
         ORDER BY t.created_at DESC
        """
    ).fetchall()
    header = ["task_id", "title", "workspace", "status", "model", "purpose", "latency_ms", "prompt_tokens", "output_tokens", "finish_reason", "created_at"]
    print(" | ".join(header))
    for row in rows:
        print(" | ".join(str(row[column]) for column in header))


if __name__ == "__main__":
    main()
