"""Executa o benchmark determinístico de mecânica runtime E2E longa.

Este harness mede o plano de controle (verificação, recuperação, continuidade e
telemetria). Ele não declara capacidade generativa: os planos são determinísticos
para que uma falha do modelo não obscureça a validação do runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import Plan, PlanStep, TaskCreate
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "benchmarks" / "e2e_long" / "tasks.yaml"


def load_tasks() -> list[dict[str, Any]]:
    tasks = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8")) or []
    if not isinstance(tasks, list) or not tasks:
        raise RuntimeError("O benchmark E2E longo exige uma lista não vazia de tarefas.")
    for task in tasks:
        steps = int(task["steps"])
        if not 10 <= steps <= 30:
            raise RuntimeError(f"{task['id']} deve exigir entre 10 e 30 etapas")
    return tasks


def make_orchestrator(root: Path) -> Orchestrator:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=root)
    db = Database(settings.db_path)
    db.initialize()
    return Orchestrator(
        settings,
        db,
        EventBus(db),
        MemoryService(db, settings),
        ModelGateway(settings),
        PolicyEngine(settings),
        ToolRegistry(settings),
    )


def write_code(path: str, content: str) -> str:
    return f"from pathlib import Path; p=Path({path!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text({content!r})"


def first_plan(case: dict[str, Any]) -> Plan:
    return Plan(
        objective=str(case["objective"]),
        steps=[
            PlanStep(id=1, action="Confirmar contexto do projeto", success_condition="task_context"),
            PlanStep(
                id=2,
                action="Executar diagnóstico que expõe falha recuperável",
                tool="python.execute",
                arguments={"code": "raise FileNotFoundError('recurso de projeto ausente')"},
                success_condition="tool_exit_zero",
            ),
        ],
        risks=["Falha inicial intencional para avaliar recuperação."],
        confidence=0.8,
    )


def revised_plan(case: dict[str, Any]) -> Plan:
    expected = list(dict(case["expected_files"]).items())
    total = int(case["steps"])
    steps = [PlanStep(id=1, action="Confirmar contexto revisado", success_condition="task_context")]
    for index in range(2, total):
        artifact_index = index - 2
        if artifact_index < len(expected):
            path, content = expected[artifact_index]
        else:
            path, content = f"work/step_{index:02d}.txt", f"{case['id']}:step:{index}:verified"
        steps.append(
            PlanStep(
                id=index,
                action=f"Produzir artefato verificável {path}",
                tool="python.execute",
                arguments={"code": write_code(str(path), str(content))},
                success_condition=f"file_contains:{path}::{content}",
            )
        )
    steps.append(PlanStep(id=total, action="Confirmar todas as etapas revisadas", success_condition="prior_steps_completed"))
    return Plan(objective=str(case["objective"]), steps=steps, risks=[], confidence=0.93)


def prepare_fixture(orchestrator: Orchestrator, workspace: str, fixture: dict[str, str]) -> None:
    root = orchestrator.tools.workspace_for(workspace)
    for path, content in fixture.items():
        target = (root / path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def evaluate_case(orchestrator: Orchestrator, task: dict[str, Any], case: dict[str, Any], elapsed_s: float) -> dict[str, Any]:
    workspace = orchestrator.tools.workspace_for(str(task["workspace"]))
    checks = []
    for relative, expected in dict(case["expected_files"]).items():
        target = workspace / relative
        checks.append({"path": relative, "exists": target.is_file(), "content_matches": target.is_file() and target.read_text(encoding="utf-8") == expected})
    plans = orchestrator.db.all("SELECT revision FROM plans WHERE task_id=? ORDER BY revision", (task["id"],))
    routed = orchestrator.db.all("SELECT decision FROM routing_decisions WHERE task_id=?", (task["id"],))
    failures = orchestrator.db.all("SELECT category FROM failures WHERE task_id=?", (task["id"],))
    task_row = orchestrator.get_task(task["id"]) or {}
    return {
        "id": case["id"],
        "status": task_row.get("status"),
        "steps_expected": int(case["steps"]),
        "steps_total": int(task_row.get("step_count") or 0),
        "replans": int(task_row.get("replan_count") or 0),
        "recovery_observed": bool(failures) and int(task_row.get("replan_count") or 0) >= 1,
        "plans": [row["revision"] for row in plans],
        "artifacts": checks,
        "artifacts_valid": all(item["exists"] and item["content_matches"] for item in checks),
        "routing_decisions": [row["decision"] for row in routed],
        "experience_reuse_count": sum(row["decision"] == "USE" for row in routed),
        "elapsed_seconds": round(elapsed_s, 3),
    }


async def run_case(orchestrator: Orchestrator, case: dict[str, Any]) -> dict[str, Any]:
    workspace = f"e2e_{case['id']}"
    prepare_fixture(orchestrator, workspace, dict(case.get("fixture") or {}))
    calls = 0

    async def planner(_task: dict[str, Any], _memories: list[dict[str, Any]], _routed: list[str] | None = None) -> Plan:
        nonlocal calls
        calls += 1
        return first_plan(case) if calls == 1 else revised_plan(case)

    original = orchestrator._make_plan
    orchestrator._make_plan = planner
    started = perf_counter()
    try:
        created = await orchestrator.create_task(
            TaskCreate(title=str(case["title"]), objective=str(case["objective"]), workspace=workspace, autonomy_mode=4)
        )
        await orchestrator.run(created["id"])
        await orchestrator.active[created["id"]]
        return evaluate_case(orchestrator, created, case, perf_counter() - started)
    finally:
        orchestrator._make_plan = original


async def run_all(tasks: list[dict[str, Any]], work_root: Path) -> dict[str, Any]:
    orchestrator = make_orchestrator(work_root)
    results = []
    for case in tasks:
        results.append(await run_case(orchestrator, case))
    successful = [item for item in results if item["status"] == "completed" and item["artifacts_valid"]]
    recovered = [item for item in results if item["recovery_observed"]]
    return {
        "benchmark": "e2e_long_runtime_v1",
        "scope": "Mecânica de runtime com planos determinísticos; não é uma medida de capacidade generativa do LLM.",
        "tasks": results,
        "metrics": {
            "task_count": len(results),
            "completion_rate": round(len(successful) / len(results), 4),
            "recovery_rate": round(len(recovered) / len(results), 4),
            "mean_steps": round(sum(item["steps_total"] for item in results) / len(results), 2),
            "mean_replans": round(sum(item["replans"] for item in results) / len(results), 2),
            "experience_reuse_count": sum(item["experience_reuse_count"] for item in results),
            "total_seconds": round(sum(item["elapsed_seconds"] for item in results), 3),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "data" / "artifacts" / "research" / "e2e_long" / "report.json")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()
    tasks = load_tasks()
    temp = Path(tempfile.mkdtemp(prefix="ultron-e2e-long-"))
    try:
        report = asyncio.run(run_all(tasks, temp))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if not args.keep_workspace:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
