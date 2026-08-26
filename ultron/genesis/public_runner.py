from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import yaml

from ultron.benchmarks.models import (
    BenchmarkRunSummary,
    BenchmarkTask,
    EvaluationResult,
    RunManifest,
    TaskExecution,
)
from ultron.configuration import Settings
from ultron.db import Database
from ultron.genesis.schemas import (
    CognitiveProgram,
    DeliberationOutput,
    FinalAnswerOutput,
)
from ultron.genesis.vm import CognitiveVM, VMExecution
from ultron.models.gateway import ModelGateway

GENESIS_PUBLIC_TASK_IDS = ("reasoning_01", "reasoning_02", "reasoning_06", "reasoning_07")
GenesisCondition = Literal["direct", "matched_compute", "program"]


@dataclass(frozen=True, slots=True)
class GenesisTaskResult:
    task: BenchmarkTask
    condition: GenesisCondition
    manifest: RunManifest
    execution: TaskExecution
    evaluation: EvaluationResult
    vm_execution: VMExecution | None = None


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
    """Verificador público derivado do enunciado; não é um operador cognitivo da VM."""
    started = perf_counter()
    if task.id not in GENESIS_PUBLIC_TASK_IDS:
        return EvaluationResult(success=False, score=0.0, evidence=[], errors=["public_task_not_in_genesis_protocol"])
    expected = _public_answer(task.objective)
    if expected is None:
        return EvaluationResult(success=False, score=0.0, evidence=[], errors=["public_verifier_cannot_derive_task"])
    actual = execution.response.casefold().strip()
    success = actual == expected
    return EvaluationResult(
        success=success,
        score=1.0 if success else 0.0,
        evidence=["public_verifier:derived_formula", "public_verifier:exact_match", f"response_length={len(execution.response)}"],
        errors=[] if success else ["public response did not exactly satisfy derived formula"],
        duration_ms=int((perf_counter() - started) * 1000),
    )


class GenesisPublicRunner:
    """Runner público que usa somente tarefas públicas e o mesmo gateway do experimento."""

    def __init__(self, settings: Settings, *, benchmark_root: Path | None = None) -> None:
        self.settings = settings
        self.root = benchmark_root or settings.root_dir / "benchmarks" / "ugib_lite"
        self.models = ModelGateway(settings)
        self.db = Database(settings.db_path)
        self.db.initialize()

    def load_tasks(self) -> list[BenchmarkTask]:
        tasks: list[BenchmarkTask] = []
        for path in sorted((self.root / "tasks").glob("*.yaml")):
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            entries = loaded if isinstance(loaded, list) else [loaded]
            tasks.extend(BenchmarkTask.model_validate(entry) for entry in entries)
        return [task for task in tasks if task.id in GENESIS_PUBLIC_TASK_IDS and not task.hidden]

    def _config_hash(self, *, model_name: str, seed: int, max_tokens: int) -> str:
        payload = {
            "settings": self.settings.raw,
            "model_name": model_name,
            "seed": seed,
            "max_tokens_total": max_tokens,
            "allowlist": [],
            "program_budget": self.settings.raw.get("genesis", {}).get("max_operators", 4),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _effective_model(self, model_name: str) -> str:
        config = self.settings.raw.get("models", {}).get("registry", {}).get(model_name, {})
        return str(config.get("model", model_name))

    @staticmethod
    def _messages(task: BenchmarkTask, condition: GenesisCondition, frame: dict[str, object] | None, call_index: int = 1) -> list[dict[str, str]]:
        system = (
            "Você é um executor de tarefa pública. Responda somente conforme o schema solicitado. "
            "Não use internet, ferramentas ou arquivos."
        )
        if condition == "direct":
            instruction = "Resolva diretamente o objetivo e retorne o schema final."
        elif condition == "matched_compute":
            instruction = f"Faça uma etapa genérica de deliberação ({call_index}/4), sem Cognitive Program específico, e mantenha uma hipótese provisória."
        else:
            instruction = f"Use o estado cognitivo produzido pelo operador ({call_index}/4) para avançar sem inventar campos fora do frame."
        context = f"Condição={condition}. {instruction}"
        if frame is not None:
            context += f"\nCognitiveFrame atual: {json.dumps(frame, ensure_ascii=False, sort_keys=True)}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{context}\n\nObjetivo público:\n{task.objective}"},
        ]

    @staticmethod
    def _deliberation_schema_message(task: BenchmarkTask, call_index: int) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "Você é uma etapa genérica de deliberação. Retorne somente o schema JSON, sem ferramentas, gabaritos ou código.",
            },
            {
                "role": "user",
                "content": f"Etapa {call_index}/4. Registre uma nota provisória e, se houver, uma resposta candidata para o objetivo público:\n{task.objective}",
            },
        ]

    @staticmethod
    def _final_schema_message(task: BenchmarkTask, notes: list[str]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "Você é o executor final de uma deliberação pareada. Retorne somente a resposta final no schema JSON; não use ferramentas ou gabaritos.",
            },
            {
                "role": "user",
                "content": f"Objetivo público:\n{task.objective}\nNotas das quatro etapas:\n{notes}",
            },
        ]

    async def _structured(self, schema: type[Any], messages: list[dict[str, str]], model_name: str, seed: int, max_tokens: int) -> Any:
        return await self.models.structured(
            schema,
            messages,
            model_name,
            seed=seed,
            max_tokens=max_tokens,
            temperature=0.2,
            repair_attempts=0,
        )

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
        call_budget: int = 1,
    ) -> GenesisTaskResult:
        if condition == "program" and program is None:
            raise ValueError("program_condition_requires_program")
        if condition != "program" and program is not None:
            raise ValueError("non_program_condition_rejects_program")
        if condition == "direct" and call_budget != 1:
            raise ValueError("direct_call_budget_must_be_one")
        if condition in {"matched_compute", "program"} and call_budget != 4:
            raise ValueError("structured_condition_call_budget_must_be_four")
        started_at = datetime.now(UTC)
        effective_model = self._effective_model(model_name)
        workspace = self.settings.artifacts_dir / "genesis-v022" / run_id / condition / task.id
        workspace.mkdir(parents=True, exist_ok=True)
        call_tokens = max(1, int(max_tokens) // call_budget)
        config_hash = self._config_hash(model_name=model_name, seed=seed, max_tokens=max_tokens)
        started = perf_counter()
        vm_execution: VMExecution | None = None
        response_text = ""
        failure_category: str | None = None
        usage_output_tokens = 0
        try:
            if condition == "direct":
                output = await asyncio.wait_for(
                    self._structured(FinalAnswerOutput, self._messages(task, condition, None, 1), model_name, seed, max_tokens),
                    timeout=task.timeout_seconds,
                )
                response_text = output.answer
            elif condition == "matched_compute":
                notes: list[str] = []
                for call_index in range(1, call_budget + 1):
                    output = await asyncio.wait_for(
                        self._structured(DeliberationOutput, self._deliberation_schema_message(task, call_index), model_name, seed, call_tokens),
                        timeout=task.timeout_seconds,
                    )
                    notes.append(output.note)
                    if output.candidate_answer:
                        response_text = output.candidate_answer
                if not response_text and notes:
                    response_text = notes[-1]
            else:
                vm_execution = await asyncio.wait_for(
                    CognitiveVM(self.models, model_name=model_name, seed=seed, max_tokens=call_tokens, max_steps=call_budget, repair_attempts=0).execute(task.objective, program),
                    timeout=task.timeout_seconds * call_budget,
                )
                if not vm_execution.valid:
                    failure_category = "VM_ERROR"
                else:
                    response_text = vm_execution.frame.candidate_answer or ""
        except TimeoutError:
            failure_category = "TIMEOUT"
        except Exception as exc:
            failure_category = "TOOL_ERROR"
            response_text = str(exc)[:500]
        execution = TaskExecution(
            task_id=task.id,
            mode="baseline",
            response=response_text,
            failure_category=failure_category,
            steps=call_budget,
            duration_ms=int((perf_counter() - started) * 1000),
            context_metrics={
                "call_budget": call_budget,
                "call_tokens": call_tokens,
                "vm_steps": vm_execution.steps if vm_execution else 0,
                "model_calls": vm_execution.model_calls if vm_execution else call_budget,
                "output_tokens": usage_output_tokens,
            },
            model=effective_model,
        )
        evaluation = evaluate_public_task(task, execution)
        manifest = RunManifest(
            run_id=f"{run_id}:{condition}:{task.id}",
            git_commit="runtime",
            model=effective_model,
            runtime="local-public-genesis-v022",
            benchmark="genesis_public",
            benchmark_version="v0.2.2",
            mode="baseline",
            seed=seed,
            config_hash=config_hash,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            platform={
                "public_only": True,
                "condition": condition,
                "vm": condition == "program",
                "call_budget": call_budget,
                "max_tokens_total": max_tokens,
                "call_tokens": call_tokens,
            },
        )
        return GenesisTaskResult(task, condition, manifest, execution, evaluation, vm_execution)

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
            average_tool_calls=float(result.execution.context_metrics.get("model_calls", 0)),
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
                str(self.settings.artifacts_dir / "genesis-v022"),
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
