"""Servidor HTTP local do UltronPro. Escuta somente 127.0.0.1 por padrão."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ultron.configuration import load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.experiments.service import ExperimentService
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    ApprovalDecision,
    BenchmarkCreate,
    ChatRequest,
    ChatResponse,
    ExperimentCreate,
    GoalCreate,
    MemoryCreate,
    MemorySearch,
    TaskCreate,
    ToolCall,
)
from ultron.telemetry.health import HealthService, Watchdog
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings(ROOT)
    db = Database(settings.db_path)
    db.initialize()
    events = EventBus(db)
    memory = MemoryService(db, settings)
    models = ModelGateway(settings)
    policy = PolicyEngine(settings)
    tools = ToolRegistry(settings)
    orchestrator = Orchestrator(settings, db, events, memory, models, policy, tools)
    experiments = ExperimentService(settings, db)
    health = HealthService(settings, db, models)
    watchdog = Watchdog(settings, orchestrator, events)
    app.state.services = {
        "settings": settings,
        "db": db,
        "events": events,
        "memory": memory,
        "models": models,
        "policy": policy,
        "tools": tools,
        "orchestrator": orchestrator,
        "experiments": experiments,
        "health": health,
        "watchdog": watchdog,
    }
    watchdog.start()
    await events.emit("system.started", {"host": settings.host, "port": settings.port})
    yield
    await orchestrator.kill_all()
    await watchdog.stop()


app = FastAPI(title="UltronPro Local API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8741"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def svc(name: str) -> Any:
    return app.state.services[name]


@app.get("/api/system/health")
async def system_health() -> dict[str, Any]:
    return await svc("health").snapshot()


@app.post("/api/system/stop")
async def stop_ultron() -> dict[str, Any]:
    count = await svc("orchestrator").kill_all()
    await svc("events").emit("system.stopped", {"tasks_cancelled": count})
    return {
        "stopped": True,
        "tasks_cancelled": count,
        "message": "STOP ULTRON executado; tarefas ativas foram canceladas e o estado foi persistido.",
    }


@app.get("/api/goals")
async def list_goals() -> list[dict[str, Any]]:
    return svc("db").all("SELECT * FROM goals ORDER BY priority DESC, updated_at DESC")


@app.post("/api/goals", status_code=201)
async def create_goal(payload: GoalCreate) -> dict[str, Any]:
    goal_id, now = str(uuid4()), timestamp()
    svc("db").execute(
        "INSERT INTO goals (id,title,description,priority,status,success_metric,created_by,created_at,updated_at) VALUES (?, ?, ?, ?, 'active', ?, 'user', ?, ?)",
        (
            goal_id,
            payload.title,
            payload.description,
            payload.priority,
            payload.success_metric,
            now,
            now,
        ),
    )
    await svc("events").emit("goal.created", {"id": goal_id, "title": payload.title})
    return svc("db").one("SELECT * FROM goals WHERE id=?", (goal_id,)) or {}


@app.get("/api/tasks")
async def list_tasks() -> list[dict[str, Any]]:
    return svc("orchestrator").list_tasks()


@app.post("/api/tasks", status_code=201)
async def create_task(payload: TaskCreate) -> dict[str, Any]:
    try:
        return await svc("orchestrator").create_task(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    task = svc("orchestrator").get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    plans = svc("db").all("SELECT * FROM plans WHERE task_id=? ORDER BY revision DESC", (task_id,))
    for plan in plans:
        plan["steps"] = svc("db").parse_json(plan.pop("steps_json"), [])
        plan["risks"] = svc("db").parse_json(plan.pop("risks_json"), [])
    task["plans"] = plans
    task["events"] = svc("events").history(task_id)
    task["tool_executions"] = svc("db").all(
        "SELECT * FROM tool_executions WHERE task_id=? ORDER BY created_at DESC", (task_id,)
    )
    task["approvals"] = svc("db").all(
        "SELECT * FROM approvals WHERE task_id=? ORDER BY requested_at DESC", (task_id,)
    )
    return task


@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str) -> dict[str, Any]:
    try:
        return await svc("orchestrator").run(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> dict[str, str]:
    if not svc("orchestrator").get_task(task_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    await svc("orchestrator").pause(task_id)
    return {"status": "paused"}


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> dict[str, Any]:
    return await run_task(task_id)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, str]:
    if not svc("orchestrator").get_task(task_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    await svc("orchestrator").cancel(task_id)
    return {"status": "cancelled"}


@app.get("/api/tasks/{task_id}/timeline")
async def task_timeline(task_id: str) -> list[dict[str, Any]]:
    return svc("events").history(task_id)


@app.post("/api/tasks/{task_id}/tools")
async def execute_tool(task_id: str, call: ToolCall) -> dict[str, Any]:
    try:
        return await svc("orchestrator").execute_tool(task_id, call)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/memories")
async def list_memories(limit: int = 100, memory_type: str | None = None) -> list[dict[str, Any]]:
    return svc("memory").list(limit, memory_type)


@app.post("/api/memories", status_code=201)
async def create_memory(payload: MemoryCreate) -> dict[str, Any]:
    item = svc("memory").create(payload)
    await svc("events").emit(
        "memory.created",
        {"id": item["id"], "type": item["type"], "summary": item["summary"]},
        payload.task_id,
    )
    return item


@app.post("/api/memories/search")
async def search_memories(payload: MemorySearch) -> list[dict[str, Any]]:
    return svc("memory").search(payload)


@app.post("/api/memories/consolidate")
async def consolidate_memories() -> dict[str, Any]:
    result = svc("memory").consolidate()
    await svc("events").emit("memory.consolidated", result)
    return result


@app.get("/api/models")
async def list_models() -> list[dict[str, Any]]:
    health = await svc("models").health()
    return [
        {**item, "health": health.get(item["name"], {})}
        for item in svc("models").configured_models()
    ]


@app.post("/api/models/test")
async def test_models() -> dict[str, Any]:
    return await svc("models").health()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    response = await svc("models").generate(
        [
            {
                "role": "system",
                "content": "Você é o assistente local UltronPro; respeite evidências, permissões e incerteza.",
            },
            {"role": "user", "content": payload.message},
        ]
    )
    svc("db").execute(
        "INSERT INTO model_calls (id,task_id,provider,model,purpose,latency_ms,prompt_tokens,output_tokens,finish_reason,created_at) VALUES (?, ?, 'local', ?, 'chat', ?, ?, ?, ?, ?)",
        (
            str(uuid4()),
            payload.task_id,
            response.model,
            response.latency_ms,
            response.usage.prompt_tokens,
            response.usage.output_tokens,
            response.finish_reason,
            timestamp(),
        ),
    )
    return ChatResponse(
        content=response.content,
        model=response.model,
        local=response.local,
        latency_ms=response.latency_ms,
    )


@app.get("/api/tools")
async def list_tools() -> list[dict[str, Any]]:
    return svc("tools").list_manifests()


@app.get("/api/approvals")
async def list_approvals(status: str = "pending") -> list[dict[str, Any]]:
    return svc("db").all(
        "SELECT * FROM approvals WHERE status=? ORDER BY requested_at DESC", (status,)
    )


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, payload: ApprovalDecision) -> dict[str, Any]:
    try:
        return await svc("orchestrator").decide_approval(
            approval_id, payload.approved, payload.note
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/experiments")
async def list_experiments() -> list[dict[str, Any]]:
    return svc("experiments").list_experiments()


@app.post("/api/experiments", status_code=201)
async def create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
    return svc("experiments").create_experiment(payload)


@app.post("/api/experiments/{experiment_id}/evaluate")
async def evaluate_experiment(
    experiment_id: str, baseline_score: float, candidate_score: float, critical_regressions: int = 0
) -> dict[str, Any]:
    try:
        return svc("experiments").evaluate_experiment(
            experiment_id, baseline_score, candidate_score, critical_regressions
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/benchmarks")
async def list_benchmarks() -> list[dict[str, Any]]:
    return svc("experiments").list_benchmarks()


@app.post("/api/benchmarks", status_code=201)
async def create_benchmark(payload: BenchmarkCreate) -> dict[str, Any]:
    return svc("experiments").create_benchmark(payload)


@app.post("/api/benchmarks/{benchmark_id}/run")
async def run_benchmark(benchmark_id: str) -> dict[str, Any]:
    try:
        result = svc("experiments").run_benchmark(benchmark_id)
        await svc("events").emit("benchmark.completed", result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/research/dashboard")
async def research_dashboard() -> dict[str, Any]:
    db = svc("db")
    runs = db.all("SELECT id,benchmark,benchmark_version,mode,model_name,seed,score,passed,total,recovery_rate,average_steps,average_tool_calls,average_latency_ms,created_at FROM research_runs ORDER BY created_at DESC LIMIT 40")
    models = db.all("SELECT model_name, COUNT(*) AS runs, ROUND(AVG(score),4) AS average_score, ROUND(AVG(average_latency_ms),1) AS average_latency_ms FROM research_runs GROUP BY model_name ORDER BY average_score DESC")
    experiments = db.all("SELECT id,hypothesis,benchmark,baseline_score,candidate_score,regression_score,status,report,updated_at FROM experiments ORDER BY updated_at DESC LIMIT 20")
    def reports(folder: Path, pattern: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(folder.glob(pattern), reverse=True)[:12]:
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return result
    cgfe = reports(svc("settings").artifacts_dir / "experiments", "*/cgfe.json")
    ablations = reports(svc("settings").artifacts_dir / "reports", "ablation_*.json")
    diagnostics = db.all("SELECT id,experiment,hypothesis_id,model_name,seed,result_json,artifact_dir,created_at FROM diagnostic_runs ORDER BY created_at DESC LIMIT 60")
    context = db.one("SELECT ROUND(AVG(total_input_tokens),2) AS average_input_tokens, COUNT(*) AS calls FROM context_metrics") or {}
    utility = db.all("SELECT memory_id, ROUND(AVG(delta),4) AS mean_delta, COUNT(*) AS observations FROM memory_utility_observations GROUP BY memory_id ORDER BY mean_delta DESC LIMIT 20")
    learn2 = [
        {**row, "result": db.parse_json(row["result_json"], {})}
        for row in diagnostics
        if row["experiment"] == "LEARN-2"
    ]
    transfer = db.all("SELECT id,model_name,seed,fresh_score,experienced_score,transfer_gain,artifact_dir,created_at FROM transfer_runs ORDER BY created_at DESC LIMIT 40")
    admission = db.one("SELECT COUNT(*) AS total, SUM(should_write) AS admitted, ROUND(AVG(admission_score),4) AS mean_score FROM memory_write_decisions") or {"total": 0, "admitted": 0, "mean_score": None}
    skills = db.all("SELECT name,success_count,failure_count,last_used,updated_at FROM skills ORDER BY updated_at DESC LIMIT 30")
    capabilities = db.all("SELECT domain,task_type,success_rate,calibrated_score,uncertainty,sample_size,updated_at FROM capability_estimates ORDER BY updated_at DESC LIMIT 40")
    world = db.one("SELECT COUNT(*) AS observations, ROUND(AVG(CASE WHEN (predicted_success>=0.5)=actual_success THEN 1.0 ELSE 0.0 END),4) AS prediction_accuracy, ROUND(AVG((predicted_success-actual_success)*(predicted_success-actual_success)),4) AS brier_score FROM world_model_observations") or {"observations": 0, "prediction_accuracy": None, "brier_score": None}
    routing = db.all("SELECT task_family,decision,COUNT(*) AS decisions,ROUND(AVG(compatibility),4) AS mean_compatibility,ROUND(AVG(expected_utility),4) AS mean_expected_utility,ROUND(AVG(observed_utility),4) AS mean_observed_utility FROM routing_decisions GROUP BY task_family,decision ORDER BY task_family,decision")
    family_utility = db.all("SELECT task_family,experience_family,mean_delta,sample_count,ci95_low,ci95_high,state,updated_at FROM family_utility_map ORDER BY task_family,experience_family")
    distillation = db.all("SELECT id,family,principle,evidence_count,success_count,failure_count,mean_utility,created_at FROM distilled_procedures ORDER BY created_at DESC LIMIT 30")
    skill_family = db.all("SELECT skill_id,family,mean_delta,sample_count,state,updated_at FROM skill_family_utility ORDER BY updated_at DESC LIMIT 60")
    utility_calibration = db.one("SELECT COUNT(*) AS observations,ROUND(AVG(ABS(predicted_utility-observed_utility)),4) AS mean_absolute_error FROM utility_predictions WHERE observed_utility IS NOT NULL") or {"observations": 0, "mean_absolute_error": None}
    transfer100_path = svc("settings").artifacts_dir / "research" / "hermes" / "transfer100" / "transfer100_json_compact_multiseed_42_51.json"
    try:
        transfer100 = json.loads(transfer100_path.read_text(encoding="utf-8")) if transfer100_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        transfer100 = {}
    return {"runs": runs, "experiments": experiments, "model_comparison": models, "cgfe": cgfe, "ablations": ablations, "diagnostics": diagnostics, "context_metrics": context, "memory_utility": utility, "learn2": learn2, "transfer": transfer, "memory_admission": admission, "skills": skills, "capabilities": capabilities, "world_model": world, "hermes": {"routing": routing, "family_utility": family_utility, "distillation": distillation, "skill_family": skill_family, "utility_calibration": utility_calibration, "transfer100": transfer100}}


@app.get("/api/system/metrics")
async def system_metrics() -> dict[str, Any]:
    health = await svc("health").snapshot()
    task_counts = svc("db").all("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status")
    return {
        "resources": health,
        "task_counts": task_counts,
        "cognitive_metrics": {
            "task_success_rate": _success_rate(),
            "memory_reuse_rate": _memory_reuse_rate(),
            "learning_delta": _learning_delta(),
        },
    }


def _success_rate() -> float:
    row = (
        svc("db").one(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS success FROM tasks"
        )
        or {}
    )
    return round((row.get("success") or 0) / row["total"], 4) if row.get("total") else 0.0


def _memory_reuse_rate() -> float:
    row = (
        svc("db").one(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN access_count > 0 THEN 1 ELSE 0 END) AS reused FROM memories"
        )
        or {}
    )
    return round((row.get("reused") or 0) / row["total"], 4) if row.get("total") else 0.0


def _learning_delta() -> float:
    rows = svc("db").all(
        "SELECT benchmark_id, MIN(score) AS first_score, MAX(score) AS best_score FROM benchmark_runs GROUP BY benchmark_id"
    )
    return round(sum(float(row["best_score"]) - float(row["first_score"]) for row in rows), 4)


@app.websocket("/ws/events")
async def events_socket(websocket: WebSocket, task_id: str | None = None) -> None:
    await websocket.accept()
    queue = svc("events").subscribe(task_id)
    try:
        await websocket.send_json(
            {"type": "system.connected", "task_id": task_id, "payload": {"local": True}}
        )
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        svc("events").unsubscribe(queue, task_id)


UI_DIST = ROOT / "apps" / "ui" / "dist"
if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def ui(path: str) -> FileResponse:
        return FileResponse(UI_DIST / "index.html")


def run() -> None:
    settings = load_settings(ROOT)
    uvicorn.run("apps.api.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
