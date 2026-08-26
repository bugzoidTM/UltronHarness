from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from ultron.configuration import load_settings
from ultron.db import Database

ROOT = Path(__file__).resolve().parents[1]


def test_life_api_runs_two_bounded_cycles_without_new_prompt(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(ROOT / "config" / "default.yaml", config_dir / "default.yaml")
    settings = load_settings(tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    db.execute(
        "INSERT INTO capability_estimates (id,domain,task_type,successes,failures,success_rate,calibrated_score,uncertainty,sample_size,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("api-estimate", "reasoning", "representation", 0, 3, 0.0, 0.25, 0.5, 3, "2026-01-01T00:00:00+00:00"),
    )
    monkeypatch.setenv("ULTRON_LIFE_PROFILE", "full")
    monkeypatch.setenv("ULTRON_MODEL_PRIMARY", "local-fallback")
    monkeypatch.setenv("ULTRON_VECTOR_ENABLED", "false")
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "ROOT", tmp_path)
    with TestClient(api_main.app) as client:
        response = client.post(
            "/api/life/runs",
            json={
                "superior_goal": "Torne-se progressivamente mais capaz de resolver problemas inéditos.",
                "workspace": "life_api",
                "autonomy_mode": 2,
            },
        )
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["human_prompts_after_initial_goal"] == 0
        assert summary["goals_created"] == 1
        assert summary["goals_completed"] == 0
        assert summary["agc"] == 0
        assert summary["ipr"] == 0.0
        assert summary["eggr"] == 0.0
        inspected = client.get(f"/api/life/runs/{summary['run_id']}")
        assert inspected.status_code == 200
        assert len(inspected.json()["cycles"]) == 2
