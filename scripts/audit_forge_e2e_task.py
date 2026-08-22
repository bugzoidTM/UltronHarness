from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DATABASE = Path("data/ultron.db")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", nargs="?")
    args = parser.parse_args()
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    task_id = args.task_id
    if task_id is None:
        latest = connection.execute("SELECT id FROM tasks WHERE workspace LIKE 'forge_%' ORDER BY created_at DESC LIMIT 1").fetchone()
        task_id = latest["id"] if latest else ""
    task = connection.execute(
        "SELECT t.*,s.state,s.context_json FROM tasks t LEFT JOIN task_state s ON s.task_id=t.id WHERE t.id=?",
        (task_id,),
    ).fetchone()
    print("TASK")
    print(json.dumps(dict(task) if task else {}, ensure_ascii=False, indent=2))
    for table, query in {
        "PLANS": "SELECT revision,steps_json,risks_json,confidence,created_at FROM plans WHERE task_id=? ORDER BY revision",
        "EXECUTIONS": "SELECT tool_name,status,arguments_json,output,error FROM tool_executions WHERE task_id=? ORDER BY created_at",
        "FAILURES": "SELECT category,message,recoverable FROM failures WHERE task_id=? ORDER BY created_at",
        "EVENTS": "SELECT event_type,payload_json,created_at FROM events WHERE task_id=? ORDER BY created_at",
    }.items():
        print(table)
        rows = connection.execute(query, (task_id,)).fetchall()
        for row in rows:
            print(json.dumps(dict(row), ensure_ascii=False))


if __name__ == "__main__":
    main()
