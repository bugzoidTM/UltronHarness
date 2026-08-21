"""Avaliadores determinísticos para tarefas do UGIB-Lite."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from ultron.benchmarks.models import BenchmarkTask, EvaluationResult, TaskExecution


class Evaluator(Protocol):
    def evaluate(
        self,
        task: BenchmarkTask,
        workspace: Path,
        execution: TaskExecution,
        private_spec: dict[str, Any],
    ) -> EvaluationResult: ...


def _result(started: float, success: bool, score: float, evidence: list[str], errors: list[str]) -> EvaluationResult:
    return EvaluationResult(
        success=success,
        score=score,
        evidence=evidence,
        errors=errors,
        duration_ms=int((perf_counter() - started) * 1000),
    )


class ExactAnswerEvaluator:
    def evaluate(
        self,
        task: BenchmarkTask,
        workspace: Path,
        execution: TaskExecution,
        private_spec: dict[str, Any],
    ) -> EvaluationResult:
        started = perf_counter()
        expected = str(private_spec["expected_answer"]).casefold().strip()
        actual = execution.response.casefold().strip()
        success = expected in actual
        evidence = [f"expected fragment={expected!r}", f"response length={len(execution.response)}"]
        errors = [] if success else ["A resposta não contém o fragmento esperado."]
        return _result(started, success, 1.0 if success else 0.0, evidence, errors)


class RegexEvaluator:
    def evaluate(
        self,
        task: BenchmarkTask,
        workspace: Path,
        execution: TaskExecution,
        private_spec: dict[str, Any],
    ) -> EvaluationResult:
        started = perf_counter()
        pattern = str(private_spec["pattern"])
        success = re.search(pattern, execution.response, re.IGNORECASE | re.DOTALL) is not None
        return _result(
            started,
            success,
            1.0 if success else 0.0,
            [f"regex={pattern!r}", f"response length={len(execution.response)}"],
            [] if success else ["A resposta não satisfez o padrão verificável."],
        )


class FileContentEvaluator:
    def evaluate(
        self,
        task: BenchmarkTask,
        workspace: Path,
        execution: TaskExecution,
        private_spec: dict[str, Any],
    ) -> EvaluationResult:
        started = perf_counter()
        relative = Path(str(private_spec["path"]))
        target = (workspace / relative).resolve()
        if not target.is_relative_to(workspace.resolve()):
            return _result(started, False, 0.0, [], ["Avaliador recebeu caminho fora do workspace."])
        if not target.is_file():
            return _result(started, False, 0.0, [], [f"Artefato esperado ausente: {relative}"])
        expected = str(private_spec.get("contains", ""))
        content = target.read_text(encoding="utf-8", errors="replace")
        success = expected.casefold() in content.casefold()
        return _result(
            started,
            success,
            1.0 if success else 0.0,
            [f"artifact={relative}", f"sha256={hashlib.sha256(content.encode()).hexdigest()}"],
            [] if success else [f"Artefato não contém o conteúdo esperado: {expected!r}"],
        )


class JsonSchemaEvaluator:
    def evaluate(
        self,
        task: BenchmarkTask,
        workspace: Path,
        execution: TaskExecution,
        private_spec: dict[str, Any],
    ) -> EvaluationResult:
        started = perf_counter()
        try:
            data = json.loads(execution.response)
        except json.JSONDecodeError as exc:
            return _result(started, False, 0.0, [], [f"JSON inválido: {exc.msg}"])
        required = set(private_spec.get("required_keys", []))
        missing = sorted(required - set(data)) if isinstance(data, dict) else sorted(required)
        success = not missing
        return _result(
            started,
            success,
            1.0 if success else 0.0,
            [f"required keys={sorted(required)}"],
            [] if success else [f"Chaves ausentes: {missing}"],
        )


EVALUATORS: dict[str, Evaluator] = {
    "exact": ExactAnswerEvaluator(),
    "regex": RegexEvaluator(),
    "file_content": FileContentEvaluator(),
    "json_schema": JsonSchemaEvaluator(),
}


def evaluate_task(
    task: BenchmarkTask,
    workspace: Path,
    execution: TaskExecution,
    private_spec: dict[str, Any],
) -> EvaluationResult:
    evaluator = EVALUATORS.get(task.evaluator)
    if not evaluator:
        return EvaluationResult(success=False, score=0.0, errors=[f"Avaliador desconhecido: {task.evaluator}"])
    return evaluator.evaluate(task, workspace, execution, private_spec)
