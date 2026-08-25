from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from ultron.configuration import load_settings
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.policy.engine import PolicyEngine
from ultron.schemas import MemoryCreate, RiskLevel


@pytest.fixture(autouse=True)
def deterministic_test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita inferência variável de modelo durante a validação automatizada."""
    monkeypatch.setenv("ULTRON_MODEL_PRIMARY", "local-fallback")
    monkeypatch.setenv("ULTRON_VECTOR_ENABLED", "false")


def test_database_initializes_and_persists(tmp_path: Path) -> None:
    db = Database(tmp_path / "ultron.db")
    db.initialize()
    db.execute(
        "INSERT INTO goals (id,title,description,priority,status,created_by,created_at,updated_at) VALUES ('g','Meta','',0.5,'active','user','now','now')"
    )
    assert db.one("SELECT title FROM goals WHERE id='g'") == {"title": "Meta"}


def test_memory_hybrid_retrieval(tmp_path: Path) -> None:
    db = Database(tmp_path / "ultron.db")
    db.initialize()
    memory = MemoryService(db)
    saved = memory.create(
        MemoryCreate(
            type="semantic",
            content="Playwright requer binários do Chromium para executar testes.",
            summary="Dependência Playwright",
            importance=0.8,
        )
    )
    results = memory.search(
        __import__("ultron.schemas", fromlist=["MemorySearch"]).MemorySearch(
            query="Chromium Playwright", limit=5
        )
    )
    assert results[0]["id"] == saved["id"]
    assert results[0]["score"] > 0


def test_policy_blocks_workspace_escape() -> None:
    settings = load_settings()
    policy = PolicyEngine(settings)
    decision = policy.evaluate(
        "file.read", {"path": "../../Windows/System32/config"}, RiskLevel.R0, 3
    )
    assert not decision.allowed
    assert decision.risk == RiskLevel.R5


def test_policy_requires_approval_for_write_in_supervised_mode() -> None:
    settings = load_settings()
    policy = PolicyEngine(settings)
    decision = policy.evaluate("file.write", {"path": "note.md"}, RiskLevel.R2, 2)
    assert decision.allowed
    assert decision.requires_approval


def test_api_health_and_task_lifecycle() -> None:
    with TestClient(app) as client:
        health = client.get("/api/system/health")
        assert health.status_code == 200
        assert health.json()["database"] is True
        task = client.post(
            "/api/tasks",
            json={
                "title": "Registrar análise",
                "objective": "Criar um registro de tarefa persistente e verificável.",
                "workspace": "test_api",
                "autonomy_mode": 2,
            },
        )
        assert task.status_code == 201
        task_id = task.json()["id"]
        started = client.post(f"/api/tasks/{task_id}/run")
        assert started.status_code == 200
        for _ in range(240):
            current = client.get(f"/api/tasks/{task_id}").json()
            if current["status"] in {"completed", "failed", "waiting_approval"}:
                break
            asyncio.run(asyncio.sleep(0.25))
        assert current["status"] in {"completed", "waiting_approval"}
        assert len(current["events"]) > 0


def test_api_life_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTRON_LIFE_PROFILE", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/life/runs",
            json={"superior_goal": "Torne-se progressivamente mais capaz"},
        )
    assert response.status_code == 409
    assert "desabilitado" in response.json()["detail"]


def test_api_stop_is_available() -> None:
    with TestClient(app) as client:
        response = client.post("/api/system/stop")
        assert response.status_code == 200
        assert response.json()["stopped"] is True


def test_supervised_write_approval_completes_and_learns() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={
                "title": "Criar arquivo supervisionado",
                "objective": "Criar um arquivo de relatório no workspace e verificar o resultado.",
                "workspace": "test_approval",
                "autonomy_mode": 2,
            },
        )
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert client.post(f"/api/tasks/{task_id}/run").status_code == 200
        for _ in range(160):
            task = client.get(f"/api/tasks/{task_id}").json()
            if task["status"] == "waiting_approval":
                break
            asyncio.run(asyncio.sleep(0.25))
        assert task["status"] == "waiting_approval"
        approval = client.get("/api/approvals").json()[0]
        assert approval["task_id"] == task_id
        decision = client.post(f"/api/approvals/{approval['id']}", json={"approved": True, "note": "Teste integrado"})
        assert decision.status_code == 200
        final = client.get(f"/api/tasks/{task_id}").json()
        assert final["status"] == "completed"
        memories = client.get("/api/memories").json()
        assert any(memory["task_id"] == task_id for memory in memories)


def test_settings_exposes_autonomy_mode() -> None:
    settings = load_settings()
    assert settings.autonomy_mode == 2
