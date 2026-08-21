"""Métricas de utilidade pareada para experimentos Hermes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RetrievalOutcome(StrEnum):
    HELPFUL = "helpful"
    NEUTRAL = "neutral"
    HARMFUL = "harmful"


@dataclass(frozen=True, slots=True)
class PairwiseResult:
    fresh_score: float
    experienced_score: float
    delta: float
    outcome: RetrievalOutcome


@dataclass(frozen=True, slots=True)
class RetrievalQuality:
    helpful_rate: float
    neutral_rate: float
    harmful_rate: float
    count: int


def evaluate_pair(fresh_score: float, experienced_score: float, epsilon: float = 0.01) -> PairwiseResult:
    delta = round(experienced_score - fresh_score, 6)
    if delta > epsilon:
        outcome = RetrievalOutcome.HELPFUL
    elif delta < -epsilon:
        outcome = RetrievalOutcome.HARMFUL
    else:
        outcome = RetrievalOutcome.NEUTRAL
    return PairwiseResult(fresh_score, experienced_score, delta, outcome)


def summarize_retrieval(results: list[PairwiseResult]) -> RetrievalQuality:
    count = len(results)
    if not count:
        return RetrievalQuality(0.0, 0.0, 0.0, 0)
    helpful = sum(result.outcome is RetrievalOutcome.HELPFUL for result in results) / count
    neutral = sum(result.outcome is RetrievalOutcome.NEUTRAL for result in results) / count
    harmful = sum(result.outcome is RetrievalOutcome.HARMFUL for result in results) / count
    return RetrievalQuality(round(helpful, 6), round(neutral, 6), round(harmful, 6), count)
