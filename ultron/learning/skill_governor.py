"""Governança local de skills; shadow-first e sem remoção automática de histórico."""
from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class SkillHealth:
    uses: int
    success_rate: float
    utility: float
    confidence: float
    recency_factor: float
    score: float
    recommended_status: str


def evaluate_skill(*, successes: int, failures: int, mean_utility: float, confidence: float, idle_days: float = 0.0) -> SkillHealth:
    uses = successes + failures
    rate = successes / uses if uses else 0.0
    recency = exp(-max(0.0, idle_days) / 30.0)
    score = rate * max(0.0, min(1.0, (mean_utility + 1) / 2)) * max(0.0, min(1.0, confidence)) * recency
    if uses >= 8 and rate >= 0.70 and mean_utility > 0:
        status = "promoted"
    elif uses >= 3 and rate >= 0.66:
        status = "probation"
    elif uses >= 5 and ((1 - rate) > 0.30 or mean_utility < 0):
        status = "degraded"
    else:
        status = "candidate"
    return SkillHealth(uses, round(rate, 4), round(mean_utility, 4), round(confidence, 4), round(recency, 4), round(score, 4), status)
