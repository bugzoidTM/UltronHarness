"""Replay de experiência verificada e métricas honestas de aprendizagem E2E."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from uuid import uuid4

from ultron.db import Database
from ultron.research.statistics import summarize


@dataclass(frozen=True, slots=True)
class ReplayProcedure:
    experience_id: str
    family: str
    problem_pattern: str
    successful_strategy: str
    failed_strategy: str
    verification_method: str
    failure_class: str


@dataclass(frozen=True, slots=True)
class LearningComparison:
    fresh_scores: tuple[float, ...]
    experienced_scores: tuple[float, ...]
    acg: float
    ci95_low: float
    ci95_high: float

    @property
    def passed(self) -> bool:
        return self.acg > 0 and self.ci95_low > 0


class ReplayCorpusBuilder:
    """Apenas experiências verificadas podem alimentar procedimentos reutilizáveis."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _generalize(text: str) -> str:
        text = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+", "<caminho>", text)
        text = re.sub(r"\bline\s+\d+\b|linha\s+\d+\b", "<linha>", text, flags=re.IGNORECASE)
        return text[:800]

    def build(self) -> list[ReplayProcedure]:
        rows = self.db.all(
            """SELECT e.id,e.strategy,e.result,e.actions_json,e.errors_json,e.lessons_json,es.family
                 FROM experiences e JOIN experience_signatures es ON es.experience_id=e.id
                WHERE e.success=1 AND es.verified=1
                ORDER BY e.created_at"""
        )
        procedures: list[ReplayProcedure] = []
        for row in rows:
            lessons = self.db.parse_json(row["lessons_json"], [])
            errors = self.db.parse_json(row["errors_json"], [])
            procedure = ReplayProcedure(
                experience_id=str(row["id"]),
                family=str(row["family"]),
                problem_pattern=self._generalize(str(row["strategy"])),
                successful_strategy=self._generalize("; ".join(str(item) for item in lessons) or str(row["result"])),
                failed_strategy=self._generalize("; ".join(str(item) for item in errors)),
                verification_method="verificador determinístico registrado",
                failure_class="recovery" if errors else "none",
            )
            procedures.append(procedure)
        return procedures

    def persist(self, procedures: list[ReplayProcedure]) -> int:
        persisted = 0
        for procedure in procedures:
            existing = self.db.one(
                "SELECT id FROM distilled_procedures WHERE family=? AND principle=?",
                (procedure.family, procedure.successful_strategy),
            )
            if existing:
                continue
            self.db.execute(
                "INSERT INTO distilled_procedures (id,family,principle,preconditions_json,recommended_actions_json,avoid_actions_json,source_experience_ids_json,evidence_count,success_count,failure_count,mean_utility,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    procedure.family,
                    procedure.successful_strategy,
                    self.db.json([procedure.problem_pattern]),
                    self.db.json([procedure.successful_strategy]),
                    self.db.json([procedure.failed_strategy] if procedure.failed_strategy else []),
                    self.db.json([procedure.experience_id]),
                    1,
                    1,
                    int(bool(procedure.failed_strategy)),
                    0.0,
                    datetime.now(UTC).isoformat(),
                ),
            )
            persisted += 1
        return persisted


def compare_learning(fresh_scores: list[float], experienced_scores: list[float]) -> LearningComparison:
    if len(fresh_scores) != len(experienced_scores) or not fresh_scores:
        raise ValueError("Comparação E2E requer séries pareadas não vazias")
    deltas = [experienced - fresh for fresh, experienced in zip(fresh_scores, experienced_scores, strict=True)]
    stats = summarize(deltas)
    return LearningComparison(
        tuple(fresh_scores),
        tuple(experienced_scores),
        round(mean(deltas), 6),
        round(stats.ci95_low, 6),
        round(stats.ci95_high, 6),
    )


def write_learning_artifact(path, comparison: LearningComparison, corpus_count: int) -> None:
    payload = {
        "metric": "ACG",
        "fresh_scores": comparison.fresh_scores,
        "experienced_scores": comparison.experienced_scores,
        "acg": comparison.acg,
        "ci95_low": comparison.ci95_low,
        "ci95_high": comparison.ci95_high,
        "gate_passed": comparison.passed,
        "verified_replay_corpus_count": corpus_count,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
