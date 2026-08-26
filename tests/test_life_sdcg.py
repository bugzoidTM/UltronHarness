from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ultron.benchmarks.models import (
    BenchmarkRunSummary,
    BenchmarkTask,
    EvaluationResult,
    RunManifest,
    TaskExecution,
    TaskRunResult,
)
from ultron.cognition.life import LifeAgencyController, LifeSDCGSummary
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.db import Database
from ultron.learning.context_builder import ContextBuilder

ROOT = Path(__file__).resolve().parents[1]


class _FakePublicRunner:
    def __init__(
        self,
        *,
        baseline_scores: tuple[float, float, float] = (0.0, 0.0, 0.0),
        candidate_scores: tuple[float, float, float] = (1.0, 1.0, 1.0),
        mutation: str | None = None,
    ) -> None:
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
                ("reasoning_06", "Calcule uma operação curta e responda somente com o número."),
                ("reasoning_07", "Complete uma sequência numérica e responda somente com o número."),
                ("reasoning_08", "Calcule um divisor comum e responda somente com o número."),
            )
        ]
        self.baseline_scores = baseline_scores
        self.candidate_scores = candidate_scores
        self.mutation = mutation
        self.calls: list[dict[str, object]] = []
        self.persisted: list[str] = []

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
        del category, experience_context, experience_limit
        assert task_id is not None
        task = next(item for item in self.tasks if item.id == task_id)
        is_candidate = bool(extra_context and extra_context.get("strategy"))
        index = [item.id for item in self.tasks].index(task.id)
        score = (self.candidate_scores if is_candidate else self.baseline_scores)[index]
        returned_task = task
        manifest_model = model_name or "local-fallback"
        manifest_seed = seed
        config_hash = "frozen-config"
        failure_category = None
        response = "resposta válida"
        evidence = [f"public-evaluator:{task.id}"]
        if self.mutation == "model" and is_candidate:
            manifest_model = "tampered-model"
        elif self.mutation == "seed" and is_candidate:
            manifest_seed += 1
        elif self.mutation == "config" and is_candidate:
            config_hash = "tampered-config"
        elif self.mutation == "budget" and is_candidate:
            returned_task = task.model_copy(update={"timeout_seconds": task.timeout_seconds + 1})
        elif self.mutation == "allowlist" and is_candidate:
            returned_task = task.model_copy(update={"allowed_tools": ["unexpected.tool"]})
        elif self.mutation == "timeout" and is_candidate:
            failure_category = "TIMEOUT"
            response = ""
            evidence = []
        elif self.mutation == "invalid_output" and is_candidate:
            response = ""
        self.calls.append(
            {
                "task_id": task.id,
                "condition": "candidate" if is_candidate else "baseline",
                "model": manifest_model,
                "seed": manifest_seed,
                "strategy": extra_context.get("strategy") if extra_context else None,
            }
        )
        now = datetime.now(UTC)
        manifest = RunManifest(
            run_id=f"fake-{len(self.calls)}",
            git_commit="test",
            model=manifest_model,
            runtime="test",
            benchmark="ugib_lite_public",
            benchmark_version="v0.2",
            mode="baseline",
            seed=manifest_seed,
            config_hash=config_hash,
            started_at=now,
            completed_at=now,
            platform={"test": True},
        )
        execution = TaskExecution(
            task_id=task.id,
            mode="baseline",
            response=response,
            failure_category=failure_category,
            model=manifest_model,
            steps=1,
            duration_ms=1,
        )
        evaluation = EvaluationResult(
            success=score >= 1.0,
            score=score,
            evidence=evidence,
            errors=[] if score >= 1.0 else ["resposta não passou no avaliador público"],
        )
        result = TaskRunResult(task=returned_task, execution=execution, evaluation=evaluation)
        summary = BenchmarkRunSummary(
            run_id=manifest.run_id,
            benchmark=manifest.benchmark,
            mode="baseline",
            score=score,
            passed=int(score >= 1.0),
            total=1,
            recovery_rate=0.0,
            first_attempt_success_rate=float(score >= 1.0),
            average_steps=1.0,
            average_tool_calls=0.0,
            average_latency_ms=1.0,
            memory_reuse_rate=0.0,
            skill_reuse_rate=0.0,
            results=[result],
        )
        return manifest, summary

    def persist_run(self, manifest: RunManifest, summary: BenchmarkRunSummary, artifact_dir: Path) -> None:
        del summary, artifact_dir
        self.persisted.append(manifest.run_id)


def _runtime(tmp_path: Path) -> tuple[Database, LifeAgencyController]:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["life"] = {
        "enabled": True,
        "max_goals": 2,
        "max_candidates": 3,
        "max_actions_per_goal": 2,
        "competence_min_sample": 2,
        "competence_max_success_rate": 0.5,
        "sdcg_model": "local-fallback",
        "sdcg_seed": 42,
        "sdcg_max_runtime_seconds": 10,
        "feature_flags": {
            "tension_detection": True,
            "goal_selection": True,
            "intention_persistence": True,
            "autonomous_continuation": True,
            "sdcg": True,
        },
        "goal_value_weights": {},
    }
    settings = Settings(raw=raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    life = LifeAgencyController(settings, db, EventBus(db), object())
    return db, life


def test_sdcg_is_disabled_by_default() -> None:
    settings = load_settings(ROOT)
    assert settings.raw["life"]["enabled"] is False
    assert settings.raw["life"]["feature_flags"]["sdcg"] is False


def _seed_gap(db: Database) -> None:
    db.execute(
        "INSERT INTO capability_estimates (id,domain,task_type,successes,failures,success_rate,calibrated_score,uncertainty,sample_size,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("gap-1", "reasoning", "representation", 0, 3, 0.0, 0.25, 0.5, 3, "2026-01-01T00:00:00+00:00"),
    )


def _summary_report(db: Database, result: LifeSDCGSummary) -> dict:
    row = db.one("SELECT report FROM experiments WHERE id=?", (result.experiment_id,))
    assert row is not None
    return db.parse_json(row["report"], {})


def test_sdcg_competence_gap_creates_one_autonomous_hypothesis(tmp_path: Path) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    tensions = [item for item in life.detect_tensions("sdcg-hypothesis") if item.kind == "COMPETENCE_GAP"]
    assert len(tensions) == 1
    hypothesis = life.formulate_strategy_hypothesis(tensions[0])
    assert hypothesis is not None
    assert hypothesis.selection_source == "life_gap_policy"
    assert hypothesis.gap_task_type == "representation"
    assert "representation" not in hypothesis.intervention.lower()
    assert "strategy" not in inspect.signature(life.run_sdcg).parameters


@pytest.mark.parametrize("mutation", ["model", "seed", "config", "budget", "allowlist", "timeout", "invalid_output"])
def test_sdcg_contract_divergence_rejects_without_writeback(tmp_path: Path, mutation: str) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    fake = _FakePublicRunner(mutation=mutation)
    life._sdcg_runner = fake
    result = asyncio.run(life.run_sdcg(run_id=f"sdcg-{mutation}"))
    assert result.status == "rejected"
    assert result.writeback_id is None
    assert result.executions in {0, 6}
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 0
    assert db.one("SELECT status FROM experiments WHERE id=?", (result.experiment_id,))["status"] == "rejected"
    assert len(fake.calls) <= 6


def test_sdcg_no_gain_persists_rejection_and_does_not_reuse(tmp_path: Path) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    fake = _FakePublicRunner(baseline_scores=(1.0, 0.0, 1.0), candidate_scores=(1.0, 0.0, 1.0))
    life._sdcg_runner = fake
    result = asyncio.run(life.run_sdcg(run_id="sdcg-no-gain"))
    assert result.status == "rejected"
    assert result.reason == "no_verified_gain"
    assert result.gain == pytest.approx(0.0)
    assert result.executions == 6
    experience = db.one("SELECT verification_state FROM experiences WHERE id=?", (f"experience-{result.experiment_id}",))
    assert experience == {"verification_state": "rejected"}
    assert db.one("SELECT COUNT(*) AS count FROM skills", ()) ["count"] == 0
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE allowed=1", ()) ["count"] == 0
    assert len(db.all("SELECT * FROM experience_pair_utility WHERE experience_id=?", (f"experience-{result.experiment_id}",))) == 3


def test_sdcg_verified_gain_promotes_and_enables_procedural_reuse(tmp_path: Path) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    fake = _FakePublicRunner()
    life._sdcg_runner = fake
    result = asyncio.run(life.run_sdcg(run_id="sdcg-gain"))
    assert result.status == "promoted"
    assert result.promoted
    assert result.gain == pytest.approx(1.0)
    assert result.executions == 6
    assert result.reusable is True
    assert len(fake.calls) == 6
    assert {call["condition"] for call in fake.calls} == {"baseline", "candidate"}
    assert all(call["model"] == "local-fallback" for call in fake.calls)
    assert all(call["seed"] == 42 for call in fake.calls)
    assert fake.calls[3]["strategy"]
    report = _summary_report(db, result)
    assert report["candidate_received_baseline_results"] is False
    assert report["hypothesis"]["selection_source"] == "life_gap_policy"
    assert db.one("SELECT verification_state FROM experiences WHERE id=?", (f"experience-{result.experiment_id}",))["verification_state"] == "verified"
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE target_type='experience' AND allowed=1", ()) ["count"] == 1
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks WHERE target_type='skill' AND allowed=1", ()) ["count"] == 1
    assert db.one("SELECT COUNT(*) AS count FROM skills WHERE verification_state='verified'", ()) ["count"] == 1


def test_sdcg_verified_experience_is_recoverable_by_context_builder_only_after_gain(tmp_path: Path) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    fake = _FakePublicRunner()
    life._sdcg_runner = fake
    result = asyncio.run(life.run_sdcg(run_id="sdcg-context"))
    assert result.promoted
    context = ContextBuilder(db)
    task = {
        "id": "context-target",
        "category": "reasoning",
        "objective": "Resolver uma tarefa curta de raciocínio.",
        "allowed_tools": [],
    }
    built = context.build(task)
    assert built.candidate_count == 1
    assert built.prefilter_count == 1
    assert built.injected is False
    assert db.one("SELECT verification_state FROM experiences WHERE id=?", (f"experience-{result.experiment_id}",))["verification_state"] == "verified"


def test_sdcg_is_public_only_and_bounded_to_six_executions(tmp_path: Path) -> None:
    db, life = _runtime(tmp_path)
    _seed_gap(db)
    fake = _FakePublicRunner()
    life._sdcg_runner = fake
    result = asyncio.run(life.run_sdcg(run_id="sdcg-bound"))
    assert result.task_ids == ("reasoning_06", "reasoning_07", "reasoning_08")
    assert result.executions == 6
    assert len(fake.calls) == 6
    assert all("private" not in str(call).lower() for call in fake.calls)
    assert db.one("SELECT benchmark FROM experiments WHERE id=?", (result.experiment_id,))["benchmark"] == "ugib_lite_public"
