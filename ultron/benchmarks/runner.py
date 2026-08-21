"""Runner local, isolado e reproduzível para o UGIB-Lite."""

from __future__ import annotations

import asyncio
import json
import platform
import random
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from subprocess import run
from time import perf_counter
from typing import Any
from uuid import uuid4

import psutil
import yaml

from ultron.benchmarks.evaluators import evaluate_task
from ultron.benchmarks.models import (
    BenchmarkMode,
    BenchmarkRunSummary,
    BenchmarkTask,
    RunManifest,
    TaskExecution,
    TaskRunResult,
)
from ultron.configuration import Settings
from ultron.db import Database
from ultron.models.gateway import ModelGateway


class UGIBLiteRunner:
    """Executa tarefas públicas sem expor os contratos privados aos modelos."""

    def __init__(self, settings: Settings, root: Path | None = None):
        self.settings = settings
        self.root = root or settings.root_dir
        self.benchmark_root = self.root / "benchmarks" / "ugib_lite"
        self.models = ModelGateway(settings)
        self.db = Database(settings.db_path)
        self.db.initialize()

    def load_manifest(self) -> dict[str, Any]:
        with (self.benchmark_root / "manifest.yaml").open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def load_tasks(self) -> list[BenchmarkTask]:
        tasks: list[BenchmarkTask] = []
        for path in sorted((self.benchmark_root / "tasks").glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            entries = payload if isinstance(payload, list) else [payload]
            tasks.extend(BenchmarkTask.model_validate(entry) for entry in entries)
        return tasks

    def _private_specs(self) -> dict[str, dict[str, Any]]:
        path = self.benchmark_root / "benchmark_private" / "answers.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _git_commit(self) -> str:
        try:
            result = run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, timeout=5)
            return result.stdout.strip() if result.returncode == 0 else "unversioned"
        except (OSError, TimeoutError):
            return "unversioned"

    def _config_hash(self) -> str:
        stable = json.dumps(self.settings.raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return sha256(stable).hexdigest()

    def _platform(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        return {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_mb": round(memory.total / 1024 / 1024, 2),
            "gpu": None,
            "vram_mb": None,
        }

    def _workspace(self, run_id: str, task_id: str) -> Path:
        path = self.settings.artifacts_dir / "benchmarks" / run_id / "workspaces" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _apply_fixture(self, task: BenchmarkTask, workspace: Path) -> None:
        if not task.workspace_fixture:
            return
        source = (self.benchmark_root / "fixtures" / task.workspace_fixture).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Fixture ausente: {task.workspace_fixture}")
        shutil.copytree(source, workspace, dirs_exist_ok=True)

    def _messages(self, task: BenchmarkTask, mode: BenchmarkMode, experience_context: list[str], experience_limit: int = 5, extra_context: dict[str, str] | None = None) -> list[dict[str, str]]:
        # Limite explícito e manifesto: o diagnóstico Top-K pode variá-lo sem alterar os demais controles.
        category_tag = f"[{task.category}]"
        relevant_experiences = [item.removeprefix(category_tag).strip() for item in list(dict.fromkeys(experience_context)) if not item.startswith("[") or item.startswith(category_tag)]
        experience_context = relevant_experiences[:max(0, experience_limit)]
        system = (
            "Você é um executor de benchmark local. Responda somente com a solução final verificável; "
            "não exponha raciocínio privado, não invente resultados e não use internet."
        )
        mode_context = {
            "baseline": "Modo baseline: responda ao objetivo sem memória e sem ferramentas.",
            "tools": f"Modo tools: escolha, quando necessário, apenas entre as ferramentas declaradas: {', '.join(task.allowed_tools) or 'nenhuma'}.",
            "ultron-fresh": f"Planeje com ferramentas permitidas ({', '.join(task.allowed_tools) or 'nenhuma'}) e não assuma memória prévia.",
            "ultron-experienced": f"Planeje com ferramentas permitidas ({', '.join(task.allowed_tools) or 'nenhuma'}). Experiências procedurais relevantes: {experience_context}." if experience_context else f"Planeje com ferramentas permitidas ({', '.join(task.allowed_tools) or 'nenhuma'}) e não assuma memória prévia.",
        }[mode]
        blocks = "\n".join(f"{name}: {value}" for name, value in (extra_context or {}).items() if value)
        user = f"{mode_context}\n\nObjetivo:\n{task.objective}\n\nContexto experimental:\n{blocks or 'nenhum'}\n\nEntregue apenas a resposta final necessária para avaliação."
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def _execute_one(
        self,
        task: BenchmarkTask,
        mode: BenchmarkMode,
        run_id: str,
        model_name: str | None,
        experience_context: list[str],
        private_spec: dict[str, Any],
        seed: int,
        experience_limit: int,
        extra_context: dict[str, str] | None,
    ) -> TaskRunResult:
        workspace = self._workspace(run_id, task.id)
        self._apply_fixture(task, workspace)
        started = perf_counter()
        messages = self._messages(task, mode, experience_context, experience_limit, extra_context)
        memory_tokens = sum(len(item) // 4 for item in list(dict.fromkeys(experience_context))[:max(0, experience_limit)])
        blocks = extra_context or {}
        context_metrics = {"system": len(messages[0]["content"]) // 4, "goal": len(task.objective) // 4, "plan": len(blocks.get("plan", "")) // 4, "memory": memory_tokens + len(blocks.get("memory", "")) // 4, "skills": len(blocks.get("skills", "")) // 4, "tools": len(",".join(task.allowed_tools)) // 4, "observations": len(blocks.get("observations", "")) // 4, "history": len(blocks.get("history", "")) // 4}
        context_metrics["total"] = sum(context_metrics.values())
        try:
            response = await asyncio.wait_for(
                self.models.generate(messages, model_name, seed=seed),
                timeout=task.timeout_seconds,
            )
            artifacts: list[str] = []
            artifact_name = private_spec.get("artifact_from_response")
            if artifact_name:
                match = __import__("re").search(r"```(?:python)?\\s*(.*?)```", response.content, __import__("re").DOTALL)
                content = match.group(1).strip() if match else response.content.strip()
                target = (workspace / str(artifact_name)).resolve()
                if target.is_relative_to(workspace.resolve()):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    artifacts.append(str(target.relative_to(workspace)))
            execution = TaskExecution(
                task_id=task.id,
                mode=mode,
                response=response.content,
                tool_calls=response.tool_calls,
                artifact_paths=artifacts,
                steps=1,
                duration_ms=response.latency_ms,
                context_metrics=context_metrics,
                model=response.model,
            )
        except TimeoutError:
            execution = TaskExecution(
                task_id=task.id,
                mode=mode,
                failure_category="TIMEOUT",
                steps=1,
                duration_ms=int((perf_counter() - started) * 1000),
                context_metrics=context_metrics,
                model=model_name or self.settings.raw["models"]["primary"],
            )
        except Exception as exc:
            execution = TaskExecution(
                task_id=task.id,
                mode=mode,
                failure_category="TOOL_ERROR",
                response=str(exc),
                steps=1,
                duration_ms=int((perf_counter() - started) * 1000),
                context_metrics=context_metrics,
                model=model_name or self.settings.raw["models"]["primary"],
            )
        evaluation = evaluate_task(task, workspace, execution, private_spec)
        return TaskRunResult(task=task, execution=execution, evaluation=evaluation)

    async def run_async(
        self,
        mode: BenchmarkMode,
        model_name: str | None = None,
        seed: int = 42,
        task_id: str | None = None,
        category: str | None = None,
        experience_context: list[str] | None = None,
        experience_limit: int = 5,
        extra_context: dict[str, str] | None = None,
    ) -> tuple[RunManifest, BenchmarkRunSummary]:
        manifest = self.load_manifest()
        random.seed(seed)
        run_id = str(uuid4())
        started = datetime.now(UTC)
        selected = self.load_tasks()
        if task_id:
            selected = [task for task in selected if task.id == task_id]
        if category:
            selected = [task for task in selected if task.category == category]
        if not selected:
            raise ValueError("Nenhuma tarefa do benchmark corresponde aos filtros solicitados.")
        specs = self._private_specs()
        results = [
            await self._execute_one(task, mode, run_id, model_name, experience_context or [], specs[task.id], seed, experience_limit, extra_context)
            for task in selected
        ]
        total = len(results)
        passed = sum(item.evaluation.success for item in results)
        recoverable = [item for item in results if item.execution.failure_category in {"TIMEOUT", "TOOL_ERROR"}]
        recovered = sum(item.execution.recovered for item in recoverable)
        summary = BenchmarkRunSummary(
            run_id=run_id,
            benchmark=str(manifest["slug"]),
            mode=mode,
            score=round(sum(item.evaluation.score for item in results) / total, 4),
            passed=passed,
            total=total,
            recovery_rate=round(recovered / len(recoverable), 4) if recoverable else 0.0,
            first_attempt_success_rate=round(passed / total, 4),
            average_steps=round(sum(item.execution.steps for item in results) / total, 4),
            average_tool_calls=round(sum(len(item.execution.tool_calls) for item in results) / total, 4),
            average_latency_ms=round(sum(item.execution.duration_ms for item in results) / total, 4),
            memory_reuse_rate=0.0 if mode != "ultron-experienced" else 1.0 if experience_context else 0.0,
            skill_reuse_rate=0.0,
            results=results,
        )
        run_manifest = RunManifest(
            run_id=run_id,
            git_commit=self._git_commit(),
            model=model_name or self.settings.raw["models"]["primary"],
            runtime="local",
            benchmark=str(manifest["slug"]),
            benchmark_version=str(manifest["version"]),
            mode=mode,
            seed=seed,
            config_hash=self._config_hash(),
            started_at=started,
            completed_at=datetime.now(UTC),
            platform=self._platform(),
        )
        return run_manifest, summary

    def persist_run(self, manifest: RunManifest, summary: BenchmarkRunSummary, artifact_dir: Path) -> None:
        """Persiste resultados de pesquisa sem depender da API em execução."""
        self.db.execute(
            "INSERT OR REPLACE INTO research_runs (id,benchmark,benchmark_version,mode,model_name,seed,config_hash,git_commit,score,passed,total,recovery_rate,average_steps,average_tool_calls,average_latency_ms,manifest_json,metrics_json,artifact_dir,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest.run_id, manifest.benchmark, manifest.benchmark_version, manifest.mode,
                manifest.model, manifest.seed, manifest.config_hash, manifest.git_commit,
                summary.score, summary.passed, summary.total, summary.recovery_rate,
                summary.average_steps, summary.average_tool_calls, summary.average_latency_ms,
                self.db.json(manifest.model_dump(mode="json")),
                self.db.json(summary.model_dump(exclude={"results"}, mode="json")),
                str(artifact_dir), manifest.completed_at.isoformat() if manifest.completed_at else manifest.started_at.isoformat(),
            ),
        )
        self.db.execute_many(
            "INSERT INTO context_metrics (id,task_id,run_id,purpose,metrics_json,total_input_tokens,output_tokens,success,steps,created_at) VALUES (?, NULL, ?, 'benchmark', ?, ?, 0, ?, ?, ?)",
            [
                (str(uuid4()), manifest.run_id, self.db.json(item.execution.context_metrics), int(item.execution.context_metrics.get("total", 0)), int(item.evaluation.success), item.execution.steps, manifest.completed_at.isoformat() if manifest.completed_at else manifest.started_at.isoformat())
                for item in summary.results
            ],
        )
        self.db.execute_many(
            "INSERT OR REPLACE INTO research_task_results (id,run_id,task_id,category,success,score,evidence_json,errors_json,execution_json,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"{manifest.run_id}:{item.task.id}", manifest.run_id, item.task.id, item.task.category,
                    int(item.evaluation.success), item.evaluation.score,
                    self.db.json(item.evaluation.evidence), self.db.json(item.evaluation.errors),
                    self.db.json(item.execution.model_dump(mode="json")),
                    manifest.completed_at.isoformat() if manifest.completed_at else manifest.started_at.isoformat(),
                )
                for item in summary.results
            ],
        )
