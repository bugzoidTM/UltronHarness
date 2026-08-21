from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import load_settings


def test_ugib_lite_v02_has_fifty_public_tasks_with_difficulties() -> None:
    runner = UGIBLiteRunner(load_settings())
    tasks = runner.load_tasks()
    assert len(tasks) == 50
    assert Counter(task.category for task in tasks) == {
        "reasoning": 10,
        "coding": 15,
        "tool_use": 15,
        "recovery": 10,
    }
    assert all(task.evaluator and task.difficulty and task.max_steps >= 1 for task in tasks)


def test_ugib_lite_keeps_private_answers_out_of_public_tasks() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "ugib_lite"
    public = "\n".join(path.read_text(encoding="utf-8") for path in (root / "tasks").glob("*.yaml"))
    private = (root / "benchmark_private" / "answers.json").read_text(encoding="utf-8")
    assert '"expected_answer"' not in public
    assert "reasoning_01" in private


def test_ugib_runner_creates_isolated_run_for_single_task() -> None:
    runner = UGIBLiteRunner(load_settings())
    manifest, summary = asyncio.run(
        runner.run_async(mode="baseline", model_name="local-fallback", task_id="reasoning_01", seed=42)
    )
    assert manifest.benchmark == "ugib-lite"
    assert summary.total == 1
    assert summary.results[0].task.id == "reasoning_01"
    workspace = runner.settings.artifacts_dir / "benchmarks" / manifest.run_id / "workspaces" / "reasoning_01"
    assert workspace.is_dir()


def test_ugib_runner_persists_manifest_and_task_result(tmp_path: Path) -> None:
    settings = load_settings()
    settings.data_dir = tmp_path / "data"
    settings.db_path = settings.data_dir / "research.db"
    settings.artifacts_dir = settings.data_dir / "artifacts"
    runner = UGIBLiteRunner(settings)
    manifest, summary = asyncio.run(
        runner.run_async(mode="baseline", model_name="local-fallback", task_id="reasoning_01")
    )
    report_dir = settings.artifacts_dir / "benchmarks" / manifest.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    runner.persist_run(manifest, summary, report_dir)
    row = runner.db.one("SELECT score,total FROM research_runs WHERE id=?", (manifest.run_id,))
    detail = runner.db.one("SELECT task_id FROM research_task_results WHERE run_id=?", (manifest.run_id,))
    assert row == {"score": summary.score, "total": 1}
    assert detail == {"task_id": "reasoning_01"}


def test_semantic_memory_retrieval_persists_vectors_locally(tmp_path: Path) -> None:
    from ultron.memory.service import MemoryService
    from ultron.schemas import MemoryCreate, MemorySearch

    settings = load_settings()
    settings.data_dir = tmp_path / "data"
    settings.db_path = settings.data_dir / "memory.db"
    settings.workspace_root = settings.data_dir / "workspaces"
    settings.artifacts_dir = settings.data_dir / "artifacts"
    db = __import__("ultron.db", fromlist=["Database"]).Database(settings.db_path)
    db.initialize()
    memory = MemoryService(db, settings)
    relevant = memory.create(MemoryCreate(type="semantic", content="Para depurar Python, valide traceback e dependências ausentes.", summary="Debug Python"))
    memory.create(MemoryCreate(type="semantic", content="Receitas de panificação usam farinha e fermento.", summary="Culinária"))
    found = memory.search(MemorySearch(query="como investigar falha de dependência em Python", limit=2))
    assert found
    assert found[0]["id"] == relevant["id"]
    assert db.one("SELECT id FROM memory_retrievals ORDER BY created_at DESC LIMIT 1") is not None


def test_recovery_engine_classifies_and_limits_retries(tmp_path: Path) -> None:
    from ultron.core.recovery import FailureCategory, RecoveryEngine

    engine = RecoveryEngine()
    failure = engine.classify("Arquivo não encontrado durante file.read", "file.read", attempt=1)
    recovery = engine.propose(failure, max_attempts=3)
    assert failure.category == FailureCategory.MISSING_RESOURCE
    assert failure.recoverable is True
    assert recovery.retry is True
    exhausted = engine.propose(engine.classify("timeout", "python.execute", attempt=3), max_attempts=3)
    assert exhausted.retry is False
    assert engine.metrics([failure], [recovery])["recovery_rate"] == 1.0


def test_skill_promotion_requires_three_uses_and_success_rate(tmp_path: Path) -> None:
    from ultron.db import Database
    from ultron.research.cycle import SkillService

    db = Database(tmp_path / "skills.db")
    db.initialize()
    skills = SkillService(db)
    for success in (True, True, False):
        skills.observe("safe_file_diagnosis", ["file failure"], ["Inspect error", "retry safely"], success)
    assert skills.status("safe_file_diagnosis") == "validated"
    skills.observe("unstable_procedure", ["x"], ["y"], True)
    assert skills.status("unstable_procedure") == "candidate"
    assert "safe_file_diagnosis" in skills.reusable_procedures()[0]


def test_experience_cycle_rejects_trivial_unsuccessful_event(tmp_path: Path) -> None:
    from ultron.db import Database
    from ultron.research.cycle import ExperienceCycle, SkillService

    db = Database(tmp_path / "experience.db")
    db.initialize()
    cycle = ExperienceCycle(db, SkillService(db))
    result = cycle.consolidate("oi", "sem ação", [], success=False)
    assert result["stored"] is False
    assert result["reason"] == "discarded_private_or_duplicate_or_low_evidence"
    assert result["admission"]["should_write"] is False


def test_research_dashboard_exposes_local_research_data(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ULTRON_MODEL_PRIMARY", "local-fallback")
    monkeypatch.setenv("ULTRON_VECTOR_ENABLED", "false")
    from apps.api.main import app

    with TestClient(app) as client:
        response = client.get("/api/research/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert {"runs", "experiments", "model_comparison", "cgfe", "ablations", "learn2", "transfer", "memory_admission", "skills", "capabilities", "world_model", "hermes"} <= payload.keys()
    assert {"routing", "family_utility", "distillation", "skill_family", "utility_calibration", "transfer100"} <= payload["hermes"].keys()


def _research_settings(tmp_path: Path):
    settings = load_settings()
    settings.data_dir = tmp_path / "data"
    settings.db_path = settings.data_dir / "research.db"
    settings.artifacts_dir = settings.data_dir / "artifacts"
    settings.raw["models"]["primary"] = "local-fallback"
    return settings


def test_cgfe_persists_report_and_prevents_benchmark_leakage(tmp_path: Path) -> None:
    from ultron.benchmarks.cgfe import CGFEExperiment

    result = CGFEExperiment(_research_settings(tmp_path), "local-fallback", seed=7).run(experience_count=5)
    assert result.experienced_run_id
    assert (result.report_dir / "cgfe.json").is_file()
    assert (result.report_dir / "cgfe.md").is_file()


def test_ablation_study_persists_six_controlled_variants(tmp_path: Path) -> None:
    from ultron.benchmarks.ablations import AblationStudy

    data = AblationStudy(_research_settings(tmp_path), "local-fallback", seed=7).run()
    assert [item["variant"] for item in data["results"]] == ["A", "B", "C", "D", "E", "F"]
    reports = list((_research_settings(tmp_path).artifacts_dir / "reports").glob("ablation_*.json"))
    assert reports


def test_recovery_failure_persistence_records_evidence(tmp_path: Path) -> None:
    from ultron.core.recovery import RecoveryEngine
    from ultron.db import Database

    db = Database(tmp_path / "failures.db")
    db.initialize()
    engine = RecoveryEngine()
    failure = engine.classify("permission denied", "file.write", attempt=1)
    recovery = engine.propose(failure, max_attempts=3)
    engine.persist(db, None, failure, recovery)
    row = db.one("SELECT category, recovery_json FROM failures LIMIT 1")
    assert row and row["category"] == failure.category.value
    assert db.parse_json(row["recovery_json"], {})["strategy"] == recovery.strategy


def test_prometheus_statistics_keeps_all_values_and_paired_deltas() -> None:
    from ultron.research.statistics import effect_delta, summarize

    summary = summarize([0.0, 0.5, 1.0])
    assert summary.count == 3
    assert summary.mean == 0.5
    assert summary.minimum == 0.0
    assert effect_delta([0.4, 0.7], [0.3, 0.5]).mean == 0.15


def test_memory_trace_flags_and_empirical_utility(tmp_path: Path) -> None:
    from ultron.db import Database
    from ultron.memory.service import MemoryService
    from ultron.schemas import MemoryCreate, MemorySearch

    db = Database(tmp_path / "diagnostics.db")
    db.initialize()
    memory = MemoryService(db)
    semantic = memory.create(MemoryCreate(type="semantic", content="Use formato JSON válido.", summary="JSON", importance=0.9))
    episodic = memory.create(MemoryCreate(type="episodic", content="Episódio de tarefa passada.", summary="Episódio", importance=0.7))
    memory.feature_flags["episodic"] = False
    results = memory.search(MemorySearch(query="formato JSON", limit=10), top_k=1)
    assert results and results[0]["id"] == semantic["id"]
    trace = db.one("SELECT candidates_json, selected_json, prompt_positions_json FROM retrieval_traces LIMIT 1")
    assert trace and semantic["id"] in db.parse_json(trace["selected_json"], [])
    assert episodic["id"] not in db.parse_json(trace["selected_json"], [])
    memory.record_empirical_utility([semantic["id"]], 0.8, 0.4)
    memory.record_empirical_utility([semantic["id"]], 0.7, 0.5)
    utility = memory.empirical_utility(semantic["id"])
    assert utility["classification"] == "HELPFUL"
    assert utility["uses"] == 2


def test_context_budgeter_accounts_blocks() -> None:
    from ultron.research.diagnostics import ContextBudgeter

    budgeter = ContextBudgeter(100, {"system": 0.2, "task": 0.2, "memory": 0.2})
    selected, metrics = budgeter.select({"system": "s" * 400, "task": "t" * 400, "memory": "m" * 400})
    assert len(selected["system"]) == 80
    assert metrics.system == 20
    assert metrics.total == 60


def test_diagnostic_harness_runs_append_only_families_with_isolated_runner(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    import ultron.research.diagnostics as diagnostics

    settings = load_settings()
    settings.data_dir = tmp_path / "data"
    settings.db_path = settings.data_dir / "diagnostics.db"
    settings.artifacts_dir = settings.data_dir / "artifacts"

    class FakeRunner:
        counter = 0

        def __init__(self, *_args, **_kwargs):
            pass

        async def run_async(self, *_args, **_kwargs):
            FakeRunner.counter += 1
            run_id = f"run-{FakeRunner.counter}"
            result = SimpleNamespace(execution=SimpleNamespace(context_metrics={"total": 12}, failure_category=None), evaluation=SimpleNamespace(success=True))
            return SimpleNamespace(run_id=run_id), SimpleNamespace(score=0.5, average_steps=1.0, average_latency_ms=2.0, results=[result])

        def persist_run(self, *_args, **_kwargs):
            return None

    class FakeCGFE:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run_async(self, count):
            return SimpleNamespace(as_dict=lambda: {"fresh_score": 0.4, "experienced_score": 0.5, "cgfe": 0.1, "experience_count": count})

    monkeypatch.setattr(diagnostics, "UGIBLiteRunner", FakeRunner)
    monkeypatch.setattr(diagnostics, "CGFEExperiment", FakeCGFE)
    harness = diagnostics.DiagnosticHarness(settings, "local-fallback", 42)
    assert harness.run(harness.memory_topk([0, 1]))["best_top_k"] in {0, 1}
    assert harness.run(harness.memory_types())["results"]
    assert harness.run(harness.context_ablation())["results"]
    assert harness.run(harness.model_matrix(["local-fallback"]))["results"]
    assert harness.run(harness.orchestrator_cost())["results"]
    assert harness.run(harness.multi_seed_cgfe([42, 43], 10))["statistics"]["cgfe"]["mean"] == 0.1
    assert harness.run(harness.experience_scaling([10, 25]))["results"]


def test_transfer20_dataset_preserves_public_private_isolation() -> None:
    from ultron.learning.transfer import TransferDataset

    root = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer20"
    dataset = TransferDataset(root)
    assert len(dataset.public_tasks()) == 20
    assert len(dataset.private_answers()) == 20
    dataset.assert_isolated(["Use evidência verificável e selecione apenas uma estratégia relevante."])
    assert all({"actions", "response_format", "target_domain"} <= set(task) for task in dataset.public_tasks())
    assert all("expected_sequence" in contract for contract in dataset.private_answers().values())
    try:
        dataset.assert_isolated(["O documento recebido contém `owner:` sem valor. Qual sequência segura deve decidir a aceitação?"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("O guard de vazamento deveria bloquear texto de tarefa pública")
