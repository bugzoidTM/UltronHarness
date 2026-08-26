from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ultron.benchmarks.models import BenchmarkTask, EvaluationResult, RunManifest, TaskExecution
from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.genesis.controller import GenesisController
from ultron.genesis.public_runner import (
    GenesisPublicRunner,
    GenesisTaskResult,
    evaluate_public_task,
)
from ultron.genesis.schemas import CognitiveProgram, CognitiveProgramBatch

ROOT = Path(__file__).resolve().parents[1]


class _FakeSynthesizer:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def generate(self, diagnosis: list[dict[str, Any]], *, max_programs: int, max_operators: int) -> CognitiveProgramBatch:
        self.calls.append(diagnosis)
        assert max_programs == 2
        assert max_operators == 4
        return CognitiveProgramBatch(
            programs=[
                CognitiveProgram(id="CP-ALPHA", operators=["REPRESENT", "VERIFY"], rationale="Verifica sem deduzir."),
                CognitiveProgram(id="CP-BETA", operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"], rationale="Representa, formula, deduz e verifica."),
            ]
        )


class _FakePublicRunner:
    def __init__(self, *, mutation: str | None = None) -> None:
        self.tasks = [
            BenchmarkTask(
                id=task_id,
                category="reasoning",
                objective=objective,
                allowed_tools=[],
                timeout_seconds=30,
                expected_artifacts=[],
                evaluator="exact",
                difficulty="easy",
                max_steps=1,
            )
            for task_id, objective in (
                ("reasoning_01", "Calcule 17 multiplicado por 3 e some 2."),
                ("reasoning_02", "A sequência é 3, 9, 27, 81. Qual é o próximo número?"),
                ("reasoning_06", "Calcule 24 dividido por 6 e some 7."),
                ("reasoning_07", "A sequência é 2, 6, 18, 54. Qual é o próximo número?"),
            )
        ]
        self.mutation = mutation
        self.calls: list[dict[str, Any]] = []
        self.persisted: list[str] = []

    def load_tasks(self) -> list[BenchmarkTask]:
        return list(self.tasks)

    async def run_one(
        self,
        *,
        task: BenchmarkTask,
        condition: str,
        run_id: str,
        model_name: str,
        seed: int,
        max_tokens: int,
        program: CognitiveProgram | None = None,
        call_budget: int = 1,
    ) -> GenesisTaskResult:
        del run_id, max_tokens, call_budget
        self.calls.append({"task_id": task.id, "condition": condition, "program_id": program.id if program else None})
        score = 1.0 if program and program.id == "CP-BETA" else 0.0
        result_model = model_name
        result_seed = seed
        result_task = task
        if self.mutation == "model" and program and task.id in {"reasoning_06", "reasoning_07"}:
            result_model = "tampered-model"
        elif self.mutation == "seed" and program and task.id in {"reasoning_06", "reasoning_07"}:
            result_seed += 1
        elif self.mutation == "contract" and program and task.id in {"reasoning_06", "reasoning_07"}:
            result_task = task.model_copy(update={"timeout_seconds": task.timeout_seconds + 1})
        now = datetime.now(UTC)
        manifest = RunManifest(
            run_id=f"genesis-fake-{len(self.calls)}",
            git_commit="test",
            model=result_model,
            runtime="test",
            benchmark="genesis_public",
            benchmark_version="v0.2",
            mode="baseline",
            seed=result_seed,
            config_hash="frozen-genesis-config",
            started_at=now,
            completed_at=now,
            platform={"public_only": True, "vm": True},
        )
        response = "53" if score else "0"
        execution = TaskExecution(task_id=task.id, mode="baseline", response=response, steps=1, duration_ms=1, model=result_model)
        evaluation = EvaluationResult(success=bool(score), score=score, evidence=["fake-public-verifier"], errors=[] if score else ["fake baseline miss"])
        return GenesisTaskResult(result_task, condition, manifest, execution, evaluation, None)

    def persist_result(self, result: GenesisTaskResult) -> None:
        self.persisted.append(result.manifest.run_id)


def _runtime(tmp_path: Path, *, writeback: bool = True) -> tuple[Database, GenesisController, _FakePublicRunner, _FakeSynthesizer]:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["genesis"] = {
        "enabled": True,
        "model": "test-model",
        "seed": 7,
        "max_runtime_seconds": 10,
        "max_programs": 2,
        "max_operators": 4,
        "max_tokens": 16,
        "diagnosis_task_ids": ["reasoning_01", "reasoning_02"],
        "holdout_task_ids": ["reasoning_06", "reasoning_07"],
        "feature_flags": {"synthesis": True, "holdout": True, "writeback": writeback},
    }
    settings = Settings(raw=raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    runner = _FakePublicRunner()
    synthesizer = _FakeSynthesizer()
    controller = GenesisController(settings, db, runner=runner, synthesizer=synthesizer, gateway=object())
    return db, controller, runner, synthesizer


def _report(db: Database, experiment_id: str) -> dict[str, Any]:
    row = db.one("SELECT report FROM experiments WHERE id=?", (experiment_id,))
    assert row is not None
    return db.parse_json(row["report"], {})


def test_genesis_is_disabled_by_default() -> None:
    settings = load_settings(ROOT)
    assert settings.raw["genesis"]["enabled"] is False
    assert settings.raw["genesis"]["max_programs"] == 2
    assert settings.raw["genesis"]["max_operators"] == 4
    assert settings.raw["genesis"]["feature_flags"] == {"synthesis": False, "holdout": False, "writeback": False}


def test_cognitive_program_schema_is_closed_and_allows_repetition() -> None:
    program = CognitiveProgram(id="CP-TEST", operators=["REPRESENT", "DEDUCT", "VERIFY", "VERIFY"], rationale="Sequência VM válida.")
    assert program.operators.count("VERIFY") == 2
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["STOP"], rationale="STOP não pertence à VM.")
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["RUN_PYTHON"], rationale="Operador proibido.")
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY", "VERIFY"], rationale="Programa longo demais.")



def test_public_verifier_requires_exact_answer_not_substring() -> None:
    task = BenchmarkTask(id="reasoning_01", category="reasoning", objective="Calcule 17 multiplicado por 3 e some 2.", evaluator="exact")
    substring = TaskExecution(task_id=task.id, mode="baseline", response="153", model="test")
    exact = TaskExecution(task_id=task.id, mode="baseline", response="53", model="test")
    assert evaluate_public_task(task, substring).success is False
    assert evaluate_public_task(task, exact).success is True


def test_genesis_selects_vm_program_without_human_argument(tmp_path: Path) -> None:
    db, controller, runner, synthesizer = _runtime(tmp_path)
    result = asyncio.run(controller.run(run_id="genesis-select"))
    assert result.status == "promoted"
    assert result.selected_program_id == "CP-BETA"
    assert result.program_ids == ("CP-ALPHA", "CP-BETA")
    assert result.executions == 10
    assert len(synthesizer.calls) == 1
    assert len(synthesizer.calls[0]) == 2
    assert len(runner.calls) == 10
    assert "selected_program_id" not in inspect.signature(controller.run).parameters
    assert "rationale" not in str(runner.calls).lower()


def test_genesis_positive_ncpg_uses_vm_holdout_and_verified_writeback(tmp_path: Path) -> None:
    db, controller, _, _ = _runtime(tmp_path)
    result = asyncio.run(controller.run(run_id="genesis-gain"))
    assert result.ncpg == pytest.approx(1.0)
    assert result.baseline_holdout_score == pytest.approx(0.0)
    assert result.selected_holdout_score == pytest.approx(1.0)
    assert result.writeback_id
    assert result.retained is True
    experience = db.one("SELECT verification_state,verified_writeback_id FROM experiences WHERE id=?", (f"genesis-experience-{result.experiment_id}",))
    assert experience["verification_state"] == "verified"
    assert experience["verified_writeback_id"] == result.writeback_id
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE target_type='experience' AND allowed=1", ()) ["count"] == 1
    report = _report(db, result.experiment_id)
    assert report["holdout_sent_to_synthesizer"] is False
    assert report["rationale_used_for_execution"] is False
    assert report["writeback"]["retained"] is True


def test_genesis_no_ncpg_rejects_and_does_not_writeback(tmp_path: Path) -> None:
    db, controller, _, _ = _runtime(tmp_path)
    result = asyncio.run(controller.run(run_id="genesis-no-gain"))
    controller.runner.tasks = controller.runner.tasks
    for task in controller.runner.tasks:
        if task.id in {"reasoning_06", "reasoning_07"}:
            pass
    controller.runner.mutation = "contract"
    rejected = asyncio.run(controller.run(run_id="genesis-no-gain-contract"))
    assert rejected.status == "rejected"
    assert rejected.writeback_id is None
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 1
    assert result.status == "promoted"


def test_genesis_adversarial_contract_change_rejects(tmp_path: Path) -> None:
    db, controller, runner, _ = _runtime(tmp_path)
    runner.mutation = "model"
    result = asyncio.run(controller.run(run_id="genesis-model"))
    assert result.status == "rejected"
    assert result.writeback_id is None
    assert result.reason.startswith("model_mismatch")
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 0


def test_genesis_rationale_is_not_in_runner_execution_messages() -> None:
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")
    program = CognitiveProgram(id="CP-TEST", operators=["REPRESENT", "DEDUCT", "VERIFY"], rationale="SEGREDO QUE NÃO PODE SER EXECUTADO")
    messages = GenesisPublicRunner._messages(task, "program", {"candidate_answer": "11", "facts": []}, 1)
    serialized = json.dumps(messages, ensure_ascii=False)
    assert program.rationale not in serialized
    assert "CognitiveFrame" in serialized


def test_genesis_public_only_source_has_no_private_runner_access(tmp_path: Path) -> None:
    source = (ROOT / "ultron" / "genesis" / "public_runner.py").read_text(encoding="utf-8")
    assert "_private_specs" not in source
    assert "private_spec" not in source
    db, controller, runner, _ = _runtime(tmp_path)
    result = asyncio.run(controller.run(run_id="genesis-public-only"))
    assert result.diagnosis_task_ids == ("reasoning_01", "reasoning_02")
    assert result.holdout_task_ids == ("reasoning_06", "reasoning_07")
    assert all(call["task_id"] in {"reasoning_01", "reasoning_02", "reasoning_06", "reasoning_07"} for call in runner.calls)
    assert db.one("SELECT benchmark FROM experiments WHERE id=?", (result.experiment_id,))["benchmark"] == "genesis_public"
