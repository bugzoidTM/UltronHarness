"""Microprobe público determinístico do LIFE v0.2.

O probe verifica apenas o mecanismo de seleção, pareamento, gate e writeback.
Não é benchmark científico, não consulta o split privado de raciocínio e não usa
um modelo para escolher a hipótese ou os scores da fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ultron.benchmarks.models import (
    BenchmarkRunSummary,
    BenchmarkTask,
    EvaluationResult,
    RunManifest,
    TaskExecution,
    TaskRunResult,
)
from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.cognition.life import LifeAgencyController
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.db import Database


class DeterministicPublicRunner:
    """Runner fake que expõe somente tarefas públicas e um avaliador fixture."""

    def __init__(self, public_runner: UGIBLiteRunner) -> None:
        self.public_runner = public_runner
        self.tasks = public_runner.load_tasks()
        self.calls: list[dict[str, Any]] = []

    def load_tasks(self) -> list[BenchmarkTask]:
        return list(self.tasks)

    async def run_async(
        self,
        *,
        mode: str,
        model_name: str | None,
        seed: int,
        task_id: str | None,
        category: str | None = None,
        experience_context: list[str] | None = None,
        experience_limit: int = 5,
        extra_context: dict[str, str] | None = None,
    ) -> tuple[RunManifest, BenchmarkRunSummary]:
        del mode, category, experience_context, experience_limit
        if task_id is None:
            raise ValueError("task_id_required")
        task = next(item for item in self.tasks if item.id == task_id)
        candidate = bool(extra_context and extra_context.get("strategy"))
        self.calls.append({"task_id": task.id, "condition": "candidate" if candidate else "baseline", "model": model_name, "seed": seed})
        now = datetime.now(UTC)
        model = model_name or "local-fallback"
        score = 1.0 if candidate else 0.0
        execution = TaskExecution(
            task_id=task.id,
            mode="baseline",
            response="fixture response",
            model=model,
            steps=1,
            duration_ms=1,
        )
        evaluation = EvaluationResult(
            success=candidate,
            score=score,
            evidence=[f"deterministic-public-verifier:{task.id}"],
            errors=[] if candidate else ["fixture baseline failure"],
        )
        manifest = RunManifest(
            run_id=f"sdcg-fixture-{len(self.calls)}",
            git_commit="development-fixture",
            model=model,
            runtime="local-deterministic-fixture",
            benchmark="ugib_lite_public",
            benchmark_version="v0.2",
            mode="baseline",
            seed=seed,
            config_hash="fixture-frozen-config",
            started_at=now,
            completed_at=now,
            platform={"fixture": True},
        )
        result = TaskRunResult(
            task=task,
            execution=execution,
            evaluation=evaluation,
        )
        summary = BenchmarkRunSummary(
            run_id=manifest.run_id,
            benchmark=manifest.benchmark,
            mode="baseline",
            score=score,
            passed=int(candidate),
            total=1,
            recovery_rate=0.0,
            first_attempt_success_rate=score,
            average_steps=1.0,
            average_tool_calls=0.0,
            average_latency_ms=1.0,
            memory_reuse_rate=0.0,
            skill_reuse_rate=0.0,
            results=[result],
        )
        return manifest, summary

    def persist_run(self, manifest: RunManifest, summary: BenchmarkRunSummary, artifact_dir: Path) -> None:
        self.public_runner.persist_run(manifest, summary, artifact_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Microprobe público determinístico do LIFE v0.2.")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/life_sdcg_probe"))
    return parser


def _isolated_settings(root: Path, output: Path) -> Settings:
    settings = load_settings(root)
    raw = deepcopy(settings.raw)
    raw["life"] = {
        **raw.get("life", {}),
        "enabled": True,
        "sdcg_model": "local-fallback",
        "sdcg_seed": 42,
        "sdcg_max_runtime_seconds": 120,
        "feature_flags": {
            **raw.get("life", {}).get("feature_flags", {}),
            "tension_detection": True,
            "goal_selection": True,
            "intention_persistence": True,
            "autonomous_continuation": True,
            "sdcg": True,
        },
    }
    isolated = Settings(raw=raw, root_dir=root)
    isolated.data_dir = output / "data"
    isolated.db_path = isolated.data_dir / "ultron.db"
    isolated.workspace_root = output / "workspaces"
    isolated.artifacts_dir = output / "artifacts"
    isolated.backups_dir = output / "backups"
    for directory in (isolated.data_dir, isolated.workspace_root, isolated.artifacts_dir, isolated.backups_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return isolated


async def _run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = _isolated_settings(root, output)
    db = Database(settings.db_path)
    db.initialize()
    public_runner = UGIBLiteRunner(settings)
    life = LifeAgencyController(settings, db, EventBus(db), object())
    life._sdcg_runner = DeterministicPublicRunner(public_runner)
    for _ in range(3):
        life.self_model.observe("reasoning", "representation", False)
    summary = await life.run_sdcg(run_id="life-sdcg-public-fixture")
    payload = {
        "scientific_use": "development_only",
        "interpretation": "Mecanismo fixture; não é evidência de generalização, lift científico ou AGI.",
        "summary": summary.__dict__ if hasattr(summary, "__dict__") else {
            "run_id": summary.run_id,
            "status": summary.status,
            "reason": summary.reason,
            "tension_id": summary.tension_id,
            "goal_id": summary.goal_id,
            "hypothesis_id": summary.hypothesis_id,
            "experiment_id": summary.experiment_id,
            "task_ids": list(summary.task_ids),
            "baseline_score": summary.baseline_score,
            "candidate_score": summary.candidate_score,
            "gain": summary.gain,
            "executions": summary.executions,
            "writeback_id": summary.writeback_id,
            "reusable": summary.reusable,
        },
        "calls": life._sdcg_runner.calls,
        "experiment": db.one("SELECT status,report FROM experiments WHERE id=?", (summary.experiment_id,)),
    }
    (output / "probe_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if summary.status == "promoted" else 1


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
