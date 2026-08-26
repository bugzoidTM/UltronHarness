"""Executa Genesis v0.2.1 No-Answer Ablation em duas tarefas públicas.

A = baseline sem VM; B = VM com projeção intermediária sem candidate_answer/verification;
C = VM completa com esses campos. O programa é CP-01 congelado do probe anterior;
não há nova síntese nem writeback nesta ablação.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ultron.benchmarks.models import BenchmarkTask, RunManifest, TaskExecution
from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.genesis.public_runner import (
    GenesisPublicRunner,
    GenesisTaskResult,
    evaluate_public_task,
)
from ultron.genesis.schemas import CognitiveProgram
from ultron.genesis.vm import CognitiveVM

FROZEN_CP_01 = CognitiveProgram(
    id="CP-01",
    operators=["REPRESENT", "DECOMPOSE", "HYPOTHESIZE", "DEDUCT"],
    rationale="Programa congelado apenas para a ablação; rationale não é executado.",
)


class FixtureAblationRunner:
    def __init__(self) -> None:
        self.tasks = [
            BenchmarkTask(id=task_id, category="reasoning", objective=objective, allowed_tools=[], timeout_seconds=30, evaluator="exact", difficulty="easy", max_steps=1)
            for task_id, objective in (
                ("reasoning_06", "Calcule 24 dividido por 6 e some 7."),
                ("reasoning_07", "A sequência é 2, 6, 18, 54. Qual é o próximo número?"),
            )
        ]

    def load_tasks(self) -> list[BenchmarkTask]:
        return list(self.tasks)

    async def run_one(self, *, task: BenchmarkTask, condition: str, run_id: str, model_name: str, seed: int, max_tokens: int, program: CognitiveProgram | None = None, frame_projection: str = "full") -> GenesisTaskResult:
        del run_id, max_tokens
        vm_execution = CognitiveVM(max_steps=len(program.operators)).execute(task.objective, program) if program else None
        if condition == "baseline":
            response = "162" if task.id == "reasoning_07" else "0"
        elif condition == "program_no_answer":
            response = "162" if task.id == "reasoning_07" else "0"
        else:
            response = vm_execution.frame.candidate_answer if vm_execution and vm_execution.valid else "0"
        now = datetime.now(UTC)
        manifest = RunManifest(run_id=f"fixture-ablation-{condition}-{task.id}", git_commit="fixture", model=model_name, runtime="fixture", benchmark="genesis_public", benchmark_version="v0.2.1", mode="baseline", seed=seed, config_hash="fixture-ablation-config", started_at=now, completed_at=now, platform={"public_only": True, "vm": bool(program), "frame_projection": frame_projection})
        projection_code = {"none": 0, "intermediate": 1, "full": 2}[frame_projection]
        execution = TaskExecution(task_id=task.id, mode="baseline", response=response, steps=1, duration_ms=1, context_metrics={"frame_projection": projection_code}, model=model_name)
        return GenesisTaskResult(task, condition, manifest, execution, evaluate_public_task(task, execution), vm_execution)

    def persist_result(self, result: GenesisTaskResult) -> None:
        del result


def _settings(root: Path, output: Path, model: str) -> Settings:
    settings = load_settings(root)
    raw = deepcopy(settings.raw)
    raw["genesis"] = {
        **raw.get("genesis", {}),
        "enabled": False,
        "model": model,
        "seed": 42,
        "max_runtime_seconds": 240,
        "max_programs": 2,
        "max_operators": 4,
        "max_tokens": 1024,
        "feature_flags": {"synthesis": False, "holdout": False, "writeback": False},
    }
    configured = Settings(raw=raw, root_dir=root)
    configured.data_dir = output / "data"
    configured.db_path = configured.data_dir / "ultron.db"
    configured.workspace_root = output / "workspaces"
    configured.artifacts_dir = output / "artifacts"
    configured.backups_dir = output / "backups"
    for directory in (configured.data_dir, configured.workspace_root, configured.artifacts_dir, configured.backups_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return configured


def _fingerprint(task: BenchmarkTask) -> str:
    payload = task.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _row(result: GenesisTaskResult, label: str) -> dict[str, Any]:
    return {
        "condition": label,
        "task_id": result.task.id,
        "score": result.evaluation.score,
        "success": result.evaluation.success,
        "response": result.execution.response,
        "model": result.manifest.model,
        "seed": result.manifest.seed,
        "config_hash": result.manifest.config_hash,
        "task_fingerprint": _fingerprint(result.task),
        "frame_projection": result.execution.context_metrics.get("frame_projection", 0),
        "vm_steps": result.vm_execution.steps if result.vm_execution else 0,
        "vm_valid": result.vm_execution is None or result.vm_execution.valid,
        "evidence": list(result.evaluation.evidence),
    }


async def _run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = _settings(root, output, args.model)
    db = Database(settings.db_path)
    db.initialize()
    if args.mode == "fixture":
        runner: Any = FixtureAblationRunner()
    else:
        runner = GenesisPublicRunner(settings)
    tasks = runner.load_tasks()
    task_map = {task.id: task for task in tasks}
    holdout_ids = ("reasoning_06", "reasoning_07")
    if any(task_id not in task_map for task_id in holdout_ids):
        raise ValueError("ablation_holdout_missing")
    rows: list[dict[str, Any]] = []
    conditions = (("A_baseline", "baseline", None, "none"), ("B_no_answer", "program_no_answer", FROZEN_CP_01, "intermediate"), ("C_full_frame", "program", FROZEN_CP_01, "full"))
    async with asyncio.timeout(int(settings.raw["genesis"]["max_runtime_seconds"])):
        for label, condition, program, projection in conditions:
            for task_id in holdout_ids:
                result = await runner.run_one(task=task_map[task_id], condition=condition, run_id=f"genesis-ablation-{args.mode}", model_name=args.model, seed=42, max_tokens=1024, program=program, frame_projection=projection)
                runner.persist_result(result)
                task_row = _row(result, label)
                rows.append(task_row)
    aggregates = {
        label: round(sum(row["score"] for row in rows if row["condition"] == label) / 2, 6)
        for label in ("A_baseline", "B_no_answer", "C_full_frame")
    }
    payload = {
        "protocol": "genesis-v0.2.1-no-answer-ablation",
        "scientific_use": "development_only" if args.mode == "fixture" else "bounded_exploratory",
        "interpretation": "Ablação de mecanismo; não é confirmação estatística nem demonstra AGI.",
        "model": args.model,
        "seed": 42,
        "max_tokens": 1024,
        "holdout_task_ids": list(holdout_ids),
        "program_id": FROZEN_CP_01.id,
        "operators": list(FROZEN_CP_01.operators),
        "rationale_used_for_execution": False,
        "synthesis_performed": False,
        "writeback_performed": False,
        "conditions": {
            "A_baseline": "sem Cognitive VM",
            "B_no_answer": "VM com facts/unknowns/constraints/hypotheses/predictions; sem candidate_answer e sem verification",
            "C_full_frame": "VM com CognitiveFrame completo",
        },
        "aggregates": aggregates,
        "delta_B_minus_A": round(aggregates["B_no_answer"] - aggregates["A_baseline"], 6),
        "delta_C_minus_A": round(aggregates["C_full_frame"] - aggregates["A_baseline"], 6),
        "rows": rows,
    }
    (output / "genesis_ablation_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis v0.2.1 No-Answer Ablation A/B/C.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_ablation"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
