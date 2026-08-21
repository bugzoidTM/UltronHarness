"""Métricas de generalização Hermes; execução permanece bloqueada até evidência intrafamília estável."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ultron.research.statistics import summarize


@dataclass(frozen=True, slots=True)
class CrossDomainTrial:
    source_domain: str
    target_domain: str
    family: str
    fresh_score: float
    experienced_score: float

    @property
    def gain(self) -> float:
        return round(self.experienced_score - self.fresh_score, 6)


@dataclass(frozen=True, slots=True)
class CrossDomainSummary:
    general_procedural_transfer_gain: float
    ci95_low: float
    ci95_high: float
    positive_families: int
    gate_passed: bool


def summarize_cross_domain(trials: list[CrossDomainTrial]) -> CrossDomainSummary:
    if not trials:
        return CrossDomainSummary(0.0, 0.0, 0.0, 0, False)
    stats = summarize(trial.gain for trial in trials)
    grouped: dict[str, list[float]] = defaultdict(list)
    for trial in trials:
        grouped[trial.family].append(trial.gain)
    positive = sum(summarize(values).mean > 0 for values in grouped.values())
    return CrossDomainSummary(round(stats.mean, 6), round(stats.ci95_low, 6), round(stats.ci95_high, 6), positive, bool(stats.mean > 0 and stats.ci95_low > 0 and positive >= 2))


@dataclass(frozen=True, slots=True)
class CrossModelTrial:
    model_name: str
    family: str
    fresh_score: float
    experienced_score: float

    @property
    def gain(self) -> float:
        return round(self.experienced_score - self.fresh_score, 6)


def model_transfer_matrix(trials: list[CrossModelTrial]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for trial in trials:
        grouped[trial.model_name][trial.family].append(trial.gain)
    for model, families in grouped.items():
        result[model] = {family: round(summarize(gains).mean, 6) for family, gains in families.items()}
    return result
