"""Executa o microprobe público bounded do Project Genesis v0.2.

Por padrão usa uma fixture determinística para validar o encadeamento e a VM.
O modo live usa o mesmo modelo local para síntese, diagnóstico e holdout, sem
carregar o runner UGIB-Lite privado.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ultron.benchmarks.models import BenchmarkTask, RunManifest, TaskExecution
from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.genesis.controller import GenesisController
from ultron.genesis.public_runner import (
    GenesisPublicRunner,
    GenesisTaskResult,
    evaluate_public_task,
)
from ultron.genesis.schemas import CognitiveProgram, CognitiveProgramBatch
from ultron.genesis.synthesizer import CognitiveProgramSynthesizer
from ultron.genesis.vm import CognitiveVM
from ultron.models.gateway import ModelGateway


class FixtureSynthesizer:
    async def generate(self, diagnosis: list[dict[str, Any]], *, max_programs: int, max_operators: int) -> CognitiveProgramBatch:
        del diagnosis
        assert max_programs == 2
        assert max_operators == 4
        return CognitiveProgramBatch(
            programs=[
                CognitiveProgram(id="CP-ALPHA", operators=["REPRESENT", "VERIFY"], rationale="Verifica sem deduzir."),
                CognitiveProgram(id="CP-BETA", operators=["REPRESENT", "DECOMPOSE", "DEDUCT", "VERIFY"], rationale="Representa, decompõe, deduz e verifica."),
            ]
        )


class FixtureRunner:
    def __init__(self, root: Path) -> None:
        del root
        self.tasks = [
            BenchmarkTask(id=task_id, category="reasoning", objective=objective, allowed_tools=[], timeout_seconds=30, evaluator="exact", difficulty="easy", max_steps=1)
            for task_id, objective in (
                ("reasoning_01", "Calcule 17 multiplicado por 3 e some 2."),
                ("reasoning_02", "A sequência é 3, 9, 27, 81. Qual é o próximo número?"),
                ("reasoning_06", "Calcule 24 dividido por 6 e some 7."),
                ("reasoning_07", "A sequência é 2, 6, 18, 54. Qual é o próximo número?"),
            )
        ]

    def load_tasks(self) -> list[BenchmarkTask]:
        return list(self.tasks)

    async def run_one(self, *, task: BenchmarkTask, condition: str, run_id: str, model_name: str, seed: int, max_tokens: int, program: CognitiveProgram | None = None) -> GenesisTaskResult:
        del run_id, max_tokens
        vm_execution = CognitiveVM(max_steps=len(program.operators)).execute(task.objective, program) if program else None
        response = vm_execution.frame.candidate_answer if vm_execution and vm_execution.valid else "0"
        now = datetime.now(UTC)
        manifest = RunManifest(run_id=f"fixture-{condition}-{task.id}", git_commit="fixture", model=model_name, runtime="fixture", benchmark="genesis_public", benchmark_version="v0.2", mode="baseline", seed=seed, config_hash="fixture-vm-config", started_at=now, completed_at=now, platform={"public_only": True, "vm": True})
        execution = TaskExecution(task_id=task.id, mode="baseline", response=response or "", steps=1, duration_ms=1, model=model_name)
        evaluation = evaluate_public_task(task, execution)
        return GenesisTaskResult(task, condition, manifest, execution, evaluation, vm_execution)

    def persist_result(self, result: GenesisTaskResult) -> None:
        del result


def _settings(root: Path, output: Path, model: str) -> Settings:
    settings = load_settings(root)
    raw = deepcopy(settings.raw)
    raw["genesis"] = {
        **raw.get("genesis", {}),
        "enabled": True,
        "model": model,
        "seed": 42,
        "max_runtime_seconds": 540,
        "max_programs": 2,
        "max_operators": 4,
        "max_tokens": 1024,
        "feature_flags": {"synthesis": True, "holdout": True, "writeback": True},
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


def _summary(result: Any) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "reason": result.reason,
        "experiment_id": result.experiment_id,
        "diagnosis_task_ids": list(result.diagnosis_task_ids),
        "holdout_task_ids": list(result.holdout_task_ids),
        "program_ids": list(result.program_ids),
        "selected_program_id": result.selected_program_id,
        "baseline_holdout_score": result.baseline_holdout_score,
        "selected_holdout_score": result.selected_holdout_score,
        "ncpg": result.ncpg,
        "executions": result.executions,
        "writeback_id": result.writeback_id,
        "retained": result.retained,
    }


async def _run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = _settings(root, output, args.model)
    db = Database(settings.db_path)
    db.initialize()
    if args.mode == "fixture":
        runner: Any = FixtureRunner(output)
        synthesizer: Any = FixtureSynthesizer()
    else:
        runner = GenesisPublicRunner(settings)
        synthesizer = CognitiveProgramSynthesizer(ModelGateway(settings), model_name=args.model, seed=42, max_tokens=1024)
    result = await GenesisController(settings, db, runner=runner, synthesizer=synthesizer).run(run_id=f"genesis-public-{args.mode}")
    experiment_row = db.one("SELECT status,report FROM experiments WHERE id=?", (result.experiment_id,))
    experiment_payload = None
    if experiment_row:
        experiment_payload = {"status": experiment_row["status"], "report": db.parse_json(experiment_row["report"], {})}
    payload = {
        "scientific_use": "development_only" if args.mode == "fixture" else "bounded_exploratory",
        "interpretation": "Fixture de mecanismo; não é evidência de capacidade." if args.mode == "fixture" else "Probe exploratório; não é confirmação estatística nem demonstra AGI.",
        "summary": _summary(result),
        "experiment": experiment_payload,
    }
    (output / "genesis_probe_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.status == "promoted" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Microprobe público bounded do Genesis v0.2 Cognitive VM.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_probe"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
