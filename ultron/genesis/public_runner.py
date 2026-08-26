from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from ultron.benchmarks.models import (
    BenchmarkRunSummary,
    BenchmarkTask,
    EvaluationResult,
    RunManifest,
    TaskExecution,
)
from ultron.configuration import Settings
from ultron.db import Database
from ultron.genesis.schemas import CognitiveProgram
from ultron.models.gateway import ModelGateway

GENESIS_PUBLIC_TASK_IDS = ("reasoning_01", "reasoning_02", "reasoning_06", "reasoning_07")
GenesisCondition = Literal["baseline", "program"]


@dataclass(frozen=True, slots=True)
class GenesisTaskResult:
    task: BenchmarkTask
    condition: GenesisCondition
    manifest: RunManifest
    execution: TaskExecution
    evaluation: EvaluationResult


def _public_answer(objective: str) -> str | None:
    arithmetic = re.search(
        r"calcule\s+(\d+)\s+(?:multiplicado por|vezes)\s+(\d+)\s+e\s+some\s+(\d+)",
        objective.casefold(),
    )
    if arithmetic:
        left, right, addend = (int(value) for value in arithmetic.groups())
        return str(left * right + addend)
    division = re.search(r"calcule\s+(\d+)\s+dividido por\s+(\d+)\s+e\s+some\s+(\d+)", objective.casefold())
    if division:
        dividend, divisor, addend = (int(value) for value in division.groups())
        if divisor and dividend % divisor == 0:
            return str(dividend // divisor + addend)
    sequence = re.search(r"sequência é\s+([\d,\s]+)\.\s+qual é o próximo", objective.casefold())
    if sequence:
        values = [int(item) for item in re.findall(r"\d+", sequence.group(1))]
        if len(values) >= 3 and values[0] and values[1] % values[0] == 0:
            ratio = values[1] // values[0]
            if all(values[index] == values[index - 1] * ratio for index in range(2, len(values))):
                return str(values[-1] * ratio)
    return None


def evaluate_public_task(task: BenchmarkTask, execution: TaskExecution) -> EvaluationResult:
    """Verificador público derivado do enunciado; não expõe a resposta ao modelo."""
    started = perf_counter()
    if task.id not in GENESIS_PUBLIC_TASK_IDS:
        return EvaluationResult(success=False, score=0.0, evidence=[], errors=["public_task_not_in_genesis_protocol"])
    expected = _public_answer(task.objective)
    if expected is None:
        return EvaluationResult(success=False, score=0.0, evidence=[], errors=["public_verifier_cannot_derive_task"])
    actual = execution.response.casefold().strip()
    success = bool(actual) and expected in actual
    return EvaluationResult(
        success=success,
        score=1.0 if success else 0.0,
        evidence=["public_verifier:derived_formula", f"response_length={len(execution.response)}"],
        errors=[] if success else ["public response did not satisfy derived formula"],
        duration_ms=int((perf_counter() - started) * 1000),
    )


class GenesisPublicRunner:
    """Runner público que nunca resolve ou carrega o diretório benchmark_private."""

    def __init__(self, settings: Settings, *, benchmark_root: Path | None = None) -> None:
        self.settings = settings
        self.root = benchmark_root or settings.root_dir / "benchmarks" / "ugib_lite"
        self.models = ModelGateway(settings)
        self.db = Database(settings.db_path)
        self.db.initialize()

    def load_tasks(self) -> list[BenchmarkTask]:
        tasks: list[BenchmarkTask] = []
        for path in sorted((self.root / "tasks").glob("*.yaml")):
            import yaml

            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            entries = loaded if isinstance(loaded, list) else [loaded]
            tasks.extend(BenchmarkTask.model_validate(entry) for entry in entries)
        return [task for task in tasks if task.id in GENESIS_PUBLIC_TASK_IDS and not task.hidden]

    def _config_hash(self, *, model_name: str, seed: int, max_tokens: int) -> str:
        payload = {
            "settings": self.settings.raw,
            "model_name": model_name,
            "seed": seed,
            "max_tokens": max_tokens,
            "allowlist": [],
            "program_budget": self.settings.raw.get("genesis", {}).get("max_operators", 6),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _effective_model(self, model_name: str) -> str:
        config = self.settings.raw.get("models", {}).get("registry", {}).get(model_name, {})
        return str(config.get("model", model_name))

    @staticmethod
    def _messages(task: BenchmarkTask, condition: GenesisCondition, program: CognitiveProgram | None) -> list[dict[str, str]]:
        system = (
            "Você é um executor de tarefa pública. Responda somente com a solução final verificável. "
            "Não use internet, ferramentas ou arquivos."
        )
        if program is None:
            context = "Modo baseline: resolva diretamente, sem programa cognitivo adicional."
        else:
            sequence = " -> ".join(program.operators)
            context = (
                "Modo programa: siga esta sequência temporária de primitivas cognitivas, sem executar código: "
                f"{sequence}. Rationale: {program.rationale}"
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Condição={condition}. {context}\n\nObjetivo público:\n{task.objective}"},
        ]

    async def run_one(
        self,
        *,
        task: BenchmarkTask,
        condition: GenesisCondition,
        run_id: str,
        model_name: str,
        seed: int,
        max_tokens: int,
        program: CognitiveProgram | None = None,
    ) -> GenesisTaskResult:
        now = datetime.now(UTC)
        effective_model = self._effective_model(model_name)
        workspace = self.settings.artifacts_dir / "genesis" / run_id / condition / task.id
        workspace.mkdir(parents=True, exist_ok=True)
        started = perf_counter()
        try:
            response = await asyncio.wait_for(
                self.models.generate(
                    self._messages(task, condition, program),
                    model_name,
                    seed=seed,
                    max_tokens=max_tokens,
                ),
                timeout=task.timeout_seconds,
            )
            execution = TaskExecution(
                task_id=task.id,
                mode="baseline",
                response=response.content,
                tool_calls=response.tool_calls,
                steps=1,
                duration_ms=response.latency_ms,
                context_metrics={"program_operators": len(program.operators) if program else 0},
                model=response.model,
            )
        except TimeoutError:
            execution = TaskExecution(
                task_id=task.id,
                mode="baseline",
                failure_category="TIMEOUT",
                steps=1,
                duration_ms=int((perf_counter() - started) * 1000),
                model=effective_model,
            )
        except Exception as exc:
            execution = TaskExecution(
                task_id=task.id,
                mode="baseline",
                response=str(exc),
                failure_category="TOOL_ERROR",
                steps=1,
                duration_ms=int((perf_counter() - started) * 1000),
                model=effective_model,
            )
        evaluation = evaluate_public_task(task, execution)
        manifest = RunManifest(
            run_id=f"{run_id}:{condition}:{task.id}",
            git_commit="runtime",
            model=execution.model,
            runtime="local-public-genesis",
            benchmark="genesis_public",
            benchmark_version="v0.1",
            mode="baseline",
            seed=seed,
            config_hash=self._config_hash(model_name=model_name, seed=seed, max_tokens=max_tokens),
            started_at=now,
            completed_at=datetime.now(UTC),
            platform={"public_only": True, "condition": condition},
        )
        return GenesisTaskResult(task, condition, manifest, execution, evaluation)

    def persist_result(self, result: GenesisTaskResult) -> None:
        summary = BenchmarkRunSummary(
            run_id=result.manifest.run_id,
            benchmark=result.manifest.benchmark,
            mode=result.manifest.mode,
            score=result.evaluation.score,
            passed=int(result.evaluation.success),
            total=1,
            recovery_rate=0.0,
            first_attempt_success_rate=float(result.evaluation.success),
            average_steps=float(result.execution.steps),
            average_tool_calls=float(len(result.execution.tool_calls)),
            average_latency_ms=float(result.execution.duration_ms),
            memory_reuse_rate=0.0,
            skill_reuse_rate=0.0,
            results=[],
        )
        self.db.execute(
            "INSERT OR REPLACE INTO research_runs (id,benchmark,benchmark_version,mode,model_name,seed,config_hash,git_commit,score,passed,total,recovery_rate,average_steps,average_tool_calls,average_latency_ms,manifest_json,metrics_json,artifact_dir,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.manifest.run_id,
                result.manifest.benchmark,
                result.manifest.benchmark_version,
                result.manifest.mode,
                result.manifest.model,
                result.manifest.seed,
                result.manifest.config_hash,
                result.manifest.git_commit,
                summary.score,
                summary.passed,
                summary.total,
                summary.recovery_rate,
                summary.average_steps,
                summary.average_tool_calls,
                summary.average_latency_ms,
                self.db.json(result.manifest.model_dump(mode="json")),
                self.db.json(summary.model_dump(exclude={"results"}, mode="json")),
                str(self.settings.artifacts_dir / "genesis"),
                result.manifest.completed_at.isoformat() if result.manifest.completed_at else result.manifest.started_at.isoformat(),
            ),
        )
        self.db.execute(
            "INSERT OR REPLACE INTO research_task_results (id,run_id,task_id,category,success,score,evidence_json,errors_json,execution_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                result.manifest.run_id,
                result.manifest.run_id,
                result.task.id,
                result.task.category,
                int(result.evaluation.success),
                result.evaluation.score,
                self.db.json(result.evaluation.evidence),
                self.db.json(result.evaluation.errors),
                self.db.json(result.execution.model_dump(mode="json")),
                result.manifest.completed_at.isoformat() if result.manifest.completed_at else result.manifest.started_at.isoformat(),
            ),
        )
