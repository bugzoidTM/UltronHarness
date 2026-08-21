"""Firewall de transferência negativa: similaridade não supera evidência empírica adversa."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean

from ultron.db import Database
from ultron.research.statistics import summarize


class FamilyUtilityState(StrEnum):
    PROMOTABLE = "PROMOTABLE"
    NEUTRAL = "NEUTRAL"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class FamilyUtility:
    task_family: str
    experience_family: str
    mean_delta: float
    sample_count: int
    ci95_low: float | None
    ci95_high: float | None
    state: FamilyUtilityState


class NegativeTransferFirewall:
    min_samples: int = 3
    promotable_threshold: float = 0.10
    harmful_threshold: float = -0.05

    @classmethod
    def classify(cls, task_family: str, experience_family: str, deltas: list[float]) -> FamilyUtility:
        if len(deltas) < cls.min_samples:
            return FamilyUtility(task_family, experience_family, round(mean(deltas), 6) if deltas else 0.0, len(deltas), None, None, FamilyUtilityState.INSUFFICIENT_DATA)
        stats = summarize(deltas)
        if stats.mean >= cls.promotable_threshold and stats.ci95_low > 0:
            state = FamilyUtilityState.PROMOTABLE
        elif stats.mean <= cls.harmful_threshold or stats.ci95_high < 0:
            state = FamilyUtilityState.HARMFUL
        else:
            state = FamilyUtilityState.NEUTRAL
        return FamilyUtility(task_family, experience_family, round(stats.mean, 6), stats.count, round(stats.ci95_low, 6), round(stats.ci95_high, 6), state)

    @classmethod
    def recalculate(cls, db: Database, task_family: str, experience_family: str) -> FamilyUtility:
        rows = db.all(
            "SELECT paired_delta FROM experience_pair_utility epu JOIN experience_signatures es ON es.experience_id=epu.experience_id JOIN task_signatures ts ON ts.id=epu.task_signature_id WHERE ts.family=? AND es.family=?",
            (task_family, experience_family),
        )
        utility = cls.classify(task_family, experience_family, [float(row["paired_delta"]) for row in rows])
        db.execute(
            "INSERT INTO family_utility_map (task_family,experience_family,mean_delta,sample_count,ci95_low,ci95_high,state,updated_at) VALUES (?,?,?,?,?,?,?,datetime('now')) ON CONFLICT(task_family,experience_family) DO UPDATE SET mean_delta=excluded.mean_delta,sample_count=excluded.sample_count,ci95_low=excluded.ci95_low,ci95_high=excluded.ci95_high,state=excluded.state,updated_at=excluded.updated_at",
            (utility.task_family, utility.experience_family, utility.mean_delta, utility.sample_count, utility.ci95_low, utility.ci95_high, utility.state.value),
        )
        return utility

    @staticmethod
    def is_blocked(db: Database, task_family: str, experience_family: str) -> bool:
        row = db.one(
            "SELECT state FROM family_utility_map WHERE task_family=? AND experience_family=?",
            (task_family, experience_family),
        )
        return bool(row and row["state"] == FamilyUtilityState.HARMFUL.value)
