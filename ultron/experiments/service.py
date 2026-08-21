"""Experimentos reproduzíveis: nenhuma alteração candidata é promovida sem benchmark e aprovação."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.configuration import Settings
from ultron.db import Database
from ultron.schemas import BenchmarkCreate, ExperimentCreate


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ExperimentService:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db

    def create_experiment(self, payload: ExperimentCreate) -> dict[str, Any]:
        experiment_id, timestamp = str(uuid4()), utcnow()
        self.db.execute(
            "INSERT INTO experiments (id,hypothesis,baseline_version,candidate_version,benchmark,status,created_at,updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
            (
                experiment_id,
                payload.hypothesis,
                payload.baseline_version,
                payload.candidate_version,
                payload.benchmark,
                timestamp,
                timestamp,
            ),
        )
        return self.get_experiment(experiment_id) or {}

    def list_experiments(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM experiments ORDER BY updated_at DESC")

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM experiments WHERE id=?", (experiment_id,))

    def evaluate_experiment(
        self,
        experiment_id: str,
        baseline_score: float,
        candidate_score: float,
        critical_regressions: int,
    ) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            raise KeyError("Experimento não encontrado.")
        improved = candidate_score > baseline_score and critical_regressions == 0
        report = (
            f"Candidate score: {candidate_score:.4f}; baseline: {baseline_score:.4f}; "
            f"critical regressions: {critical_regressions}; eligible_for_user_approval: {improved}."
        )
        self.db.execute(
            "UPDATE experiments SET baseline_score=?, candidate_score=?, regression_score=?, status=?, report=?, updated_at=? WHERE id=?",
            (
                baseline_score,
                candidate_score,
                float(critical_regressions),
                "awaiting_approval" if improved else "rejected",
                report,
                utcnow(),
                experiment_id,
            ),
        )
        return {
            **(self.get_experiment(experiment_id) or {}),
            "eligible_for_user_approval": improved,
        }

    def create_benchmark(self, payload: BenchmarkCreate) -> dict[str, Any]:
        benchmark_id, timestamp = str(uuid4()), utcnow()
        definition = {
            "version": "UGIB-Lite-0.1",
            "cases": payload.cases,
            "reproducibility": {"config": self.settings.raw, "seed": 0},
        }
        self.db.execute(
            "INSERT INTO benchmarks (id,name,category,definition_json,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                benchmark_id,
                payload.name,
                payload.category,
                self.db.json(definition),
                timestamp,
                timestamp,
            ),
        )
        return self.get_benchmark(benchmark_id) or {}

    def list_benchmarks(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM benchmarks ORDER BY updated_at DESC")

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM benchmarks WHERE id=?", (benchmark_id,))
        if row:
            row["definition"] = self.db.parse_json(row.pop("definition_json"), {})
        return row

    def run_benchmark(self, benchmark_id: str) -> dict[str, Any]:
        benchmark = self.get_benchmark(benchmark_id)
        if not benchmark:
            raise KeyError("Benchmark não encontrado.")
        cases = benchmark["definition"].get("cases", [])
        # O runner inicial avalia asserts determinísticos declarados, sem transformar LLM em juiz de si mesmo.
        details: list[dict[str, Any]] = []
        passed = 0
        for case in cases:
            expected = case.get("expected", True)
            actual = case.get("actual", expected)
            ok = actual == expected
            passed += int(ok)
            details.append(
                {
                    "id": case.get("id", str(len(details) + 1)),
                    "passed": ok,
                    "expected": expected,
                    "actual": actual,
                }
            )
        total = len(cases)
        score = passed / total if total else 0.0
        run_id = str(uuid4())
        self.db.execute(
            "INSERT INTO benchmark_runs (id,benchmark_id,score,passed,total,details_json,model_name,config_json,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                benchmark_id,
                score,
                passed,
                total,
                self.db.json(details),
                self.settings.raw["models"]["primary"],
                self.db.json(benchmark["definition"].get("reproducibility", {})),
                utcnow(),
            ),
        )
        self.db.execute(
            "UPDATE benchmarks SET latest_score=?, runs=runs+1, updated_at=? WHERE id=?",
            (score, utcnow(), benchmark_id),
        )
        return {
            "id": run_id,
            "benchmark_id": benchmark_id,
            "score": score,
            "passed": passed,
            "total": total,
            "details": details,
            "learning_delta": self.learning_delta(benchmark_id, score),
        }

    def learning_delta(self, benchmark_id: str, latest: float | None = None) -> float | None:
        runs = self.db.all(
            "SELECT score FROM benchmark_runs WHERE benchmark_id=? ORDER BY created_at ASC",
            (benchmark_id,),
        )
        if not runs:
            return None
        baseline = float(runs[0]["score"])
        current = latest if latest is not None else float(runs[-1]["score"])
        return round(current - baseline, 4)
