"""Roteamento de skills por família; toda ativação começa shadow/experimental."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean

from ultron.db import Database
from ultron.research.statistics import summarize


class SkillFamilyState(StrEnum):
    ACTIVE_CANDIDATE = "ACTIVE_CANDIDATE"
    BLOCKED = "BLOCKED"
    ABSTAIN = "ABSTAIN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class SkillFamilyUtility:
    skill_id: str
    family: str
    mean_delta: float
    sample_count: int
    state: SkillFamilyState


class FamilySkillRouter:
    min_samples = 3

    @classmethod
    def classify(cls, skill_id: str, family: str, deltas: list[float]) -> SkillFamilyUtility:
        average = round(mean(deltas), 6) if deltas else 0.0
        if len(deltas) < cls.min_samples:
            return SkillFamilyUtility(skill_id, family, average, len(deltas), SkillFamilyState.INSUFFICIENT_DATA)
        stats = summarize(deltas)
        if stats.mean >= 0.10 and stats.ci95_low > 0:
            state = SkillFamilyState.ACTIVE_CANDIDATE
        elif stats.mean <= -0.05 or stats.ci95_high < 0:
            state = SkillFamilyState.BLOCKED
        else:
            state = SkillFamilyState.ABSTAIN
        return SkillFamilyUtility(skill_id, family, round(stats.mean, 6), stats.count, state)

    @staticmethod
    def persist(db: Database, utility: SkillFamilyUtility) -> None:
        db.execute(
            "INSERT INTO skill_family_utility (skill_id,family,mean_delta,sample_count,state,updated_at) VALUES (?,?,?,?,?,datetime('now')) ON CONFLICT(skill_id,family) DO UPDATE SET mean_delta=excluded.mean_delta,sample_count=excluded.sample_count,state=excluded.state,updated_at=excluded.updated_at",
            (utility.skill_id, utility.family, utility.mean_delta, utility.sample_count, utility.state.value),
        )

    @staticmethod
    def can_use(db: Database, skill_id: str, family: str) -> bool:
        row = db.one("SELECT state FROM skill_family_utility WHERE skill_id=? AND family=?", (skill_id, family))
        return bool(row and row["state"] == SkillFamilyState.ACTIVE_CANDIDATE.value)
