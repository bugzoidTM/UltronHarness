from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ultron.benchmarks.models import (
    BenchmarkTask,
    EvaluationResult,
    RunManifest,
    TaskExecution,
)
from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.genesis.controller import GenesisController
from ultron.genesis.public_runner import GenesisTaskResult
from ultron.genesis.schemas import CognitiveProgram, CognitiveProgramBatch

ROOT = Path(__file__).resolve().parents[1]


class _FakeSynthesizer:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def generate(self, diagnosis: list[dict[str, Any]], *, max_programs: int, max_operators: int) -> CognitiveProgramBatch:
        self.calls.append(diagnosis)
        assert max_programs == 3
        assert max_operators == 6
        return CognitiveProgramBatch(
            programs=[
                CognitiveProgram(id="CP-ALPHA", operators=["OBSERVE", "VERIFY", "STOP"], rationale="Organiza observação e verifica o resultado."),
                CognitiveProgram(id="CP-BETA", operators=["OBSERVE", "REPRESENT", "DEDUCT", "VERIFY", "STOP"], rationale="Representa a estrutura antes da dedução e verifica a resposta."),
                CognitiveProgram(id="CP-GAMMA", operators=["OBSERVE", "DECOMPOSE", "VERIFY", "STOP"], rationale="Divide a tarefa e verifica a composição final."),
            ]
        )


class _FakePublicRunner:
    def __init__(self, *, selected_score: float = 1.0, mutation: str | None = None) -> None:
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
        self.selected_score = selected_score
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
    ) -> GenesisTaskResult:
        del max_tokens
        self.calls.append({"task_id": task.id, "condition": condition, "program_id": program.id if program else None})
        is_beta = program is not None and program.id == "CP-BETA"
        score = self.selected_score if is_beta else 0.0
        result_model = model_name
        result_seed = seed
        fingerprint_task = task
        if self.mutation == "model" and is_beta and task.id in {"reasoning_06", "reasoning_07"}:
            result_model = "tampered-model"
        elif self.mutation == "seed" and is_beta and task.id in {"reasoning_06", "reasoning_07"}:
            result_seed += 1
        elif self.mutation == "contract" and is_beta and task.id in {"reasoning_06", "reasoning_07"}:
            fingerprint_task = task.model_copy(update={"timeout_seconds": task.timeout_seconds + 1})
        now = datetime.now(UTC)
        manifest = RunManifest(
            run_id=f"genesis-fake-{len(self.calls)}",
            git_commit="test",
            model=result_model,
            runtime="test",
            benchmark="genesis_public",
            benchmark_version="v0.1",
            mode="baseline",
            seed=result_seed,
            config_hash="frozen-genesis-config",
            started_at=now,
            completed_at=now,
            platform={"public_only": True},
        )
        execution = TaskExecution(
            task_id=task.id,
            mode="baseline",
            response="1" if score else "0",
            steps=1,
            duration_ms=1,
            model=result_model,
        )
        evaluation = EvaluationResult(
            success=bool(score),
            score=score,
            evidence=["fake-public-verifier"],
            errors=[] if score else ["diagnostic or baseline miss"],
        )
        return GenesisTaskResult(fingerprint_task, condition, manifest, execution, evaluation)

    def persist_result(self, result: GenesisTaskResult) -> None:
        self.persisted.append(result.manifest.run_id)


def _runtime(tmp_path: Path, *, writeback: bool = True) -> tuple[Database, GenesisController, _FakePublicRunner, _FakeSynthesizer]:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["genesis"] = {
        "enabled": True,
        "model": "test-model",
        "seed": 7,
        "max_runtime_seconds": 10,
        "max_programs": 3,
        "max_operators": 6,
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
    assert settings.raw["genesis"]["feature_flags"] == {"synthesis": False, "holdout": False, "writeback": False}


def test_cognitive_program_schema_is_closed_and_bounded() -> None:
    batch = CognitiveProgramBatch(
        programs=[CognitiveProgram(id="CP-TEST", operators=["OBSERVE", "STOP"], rationale="Sequência mínima válida.")]
    )
    assert batch.programs[0].operators == ["OBSERVE", "STOP"]
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["RUN_PYTHON", "STOP"], rationale="Operador proibido.")
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["OBSERVE", "STOP", "VERIFY"], rationale="STOP não é terminal.")


def test_genesis_selects_model_generated_program_without_human_argument(tmp_path: Path) -> None:
    db, controller, runner, synthesizer = _runtime(tmp_path)
    result = asyncio.run(controller.run(run_id="genesis-select"))
    assert result.status == "promoted"
    assert result.selected_program_id == "CP-BETA"
    assert result.program_ids == ("CP-ALPHA", "CP-BETA", "CP-GAMMA")
    assert result.executions == 12
    assert len(synthesizer.calls) == 1
    assert len(synthesizer.calls[0]) == 2
    assert len(runner.calls) == 12
    assert "selected_program_id" not in inspect.signature(controller.run).parameters
    assert "holdout" not in str(synthesizer.calls[0]).lower()


def test_genesis_positive_ncpg_uses_holdout_and_verified_writeback(tmp_path: Path) -> None:
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
    assert report["human_selected_program"] is False
    assert report["writeback"]["retained"] is True


def test_genesis_no_ncpg_rejects_and_does_not_writeback(tmp_path: Path) -> None:
    db, controller, _, _ = _runtime(tmp_path)
    controller.runner.selected_score = 0.0
    result = asyncio.run(controller.run(run_id="genesis-no-gain"))
    assert result.status == "rejected"
    assert result.reason == "no_positive_ncpg"
    assert result.writeback_id is None
    assert db.one("SELECT COUNT(*) AS count FROM experiences", ()) ["count"] == 0
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 0


@pytest.mark.parametrize("mutation", ["model", "seed", "contract"])
def test_genesis_adversarial_contract_change_rejects(tmp_path: Path, mutation: str) -> None:
    db, controller, runner, _ = _runtime(tmp_path)
    runner.mutation = mutation
    result = asyncio.run(controller.run(run_id=f"genesis-{mutation}"))
    assert result.status == "rejected"
    assert result.writeback_id is None
    assert result.reason.startswith(("model_mismatch", "seed_mismatch", "task_fingerprint_mismatch"))
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 0


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
