"""Estimativa auditável de Expected Experience Utility (EEU)."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from ultron.db import Database
from ultron.learning.experience_matcher import MatchResult


@dataclass(frozen=True, slots=True)
class UtilityEstimate:
    experience_id: str
    compatibility: float
    historical_mean_delta: float
    confidence_factor: float
    expected_utility: float
    sample_count: int
    uncertainty: float


class ExperienceUtilityModel:
    """Não consulta LLM; aprende somente de deltas de pares verificáveis."""

    @staticmethod
    def estimate(db: Database, experience_id: str, match: MatchResult) -> UtilityEstimate:
        row = db.one(
            "SELECT COUNT(*) AS sample_count, COALESCE(AVG(paired_delta),0) AS mean_delta FROM experience_pair_utility WHERE experience_id=?",
            (experience_id,),
        ) or {"sample_count": 0, "mean_delta": 0.0}
        sample_count = int(row["sample_count"])
        mean_delta = float(row["mean_delta"])
        confidence = sample_count / (sample_count + 3.0)
        uncertainty = 1.0 / sqrt(sample_count + 1.0)
        expected = mean_delta * confidence * match.score
        return UtilityEstimate(
            experience_id=experience_id,
            compatibility=match.score,
            historical_mean_delta=round(mean_delta, 6),
            confidence_factor=round(confidence, 6),
            expected_utility=round(expected, 6),
            sample_count=sample_count,
            uncertainty=round(uncertainty, 6),
        )

    @staticmethod
    def record_pair_outcome(
        db: Database,
        *,
        task_signature_id: str,
        experience_id: str,
        fresh_score: float,
        experienced_score: float,
        run_id: str | None = None,
    ) -> float:
        from datetime import UTC, datetime
        from uuid import uuid4

        delta = round(experienced_score - fresh_score, 6)
        db.execute(
            "INSERT INTO experience_pair_utility (id,run_id,task_signature_id,experience_id,fresh_score,experienced_score,paired_delta,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                run_id,
                task_signature_id,
                experience_id,
                fresh_score,
                experienced_score,
                delta,
                datetime.now(UTC).isoformat(),
            ),
        )
        return delta
