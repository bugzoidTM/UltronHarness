"""Destilação procedural determinística com proveniência obrigatória."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import mean
from uuid import uuid4

from ultron.db import Database


@dataclass(frozen=True, slots=True)
class ProcedureEvidence:
    experience_id: str
    family: str
    principle: str
    preconditions: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    avoid_actions: tuple[str, ...]
    success: bool
    utility: float
    verified: bool


@dataclass(frozen=True, slots=True)
class DistilledProcedure:
    id: str
    family: str
    principle: str
    preconditions: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    avoid_actions: tuple[str, ...]
    source_experience_ids: tuple[str, ...]
    evidence_count: int
    success_count: int
    failure_count: int
    mean_utility: float


class ExperienceDistiller:
    min_compatible_experiences = 3

    @classmethod
    def distill(cls, evidence: Iterable[ProcedureEvidence]) -> DistilledProcedure | None:
        items = [item for item in evidence if item.verified]
        if len(items) < cls.min_compatible_experiences:
            return None
        families = {item.family for item in items}
        principles = {item.principle for item in items}
        if len(families) != 1 or len(principles) != 1:
            return None
        if mean(item.utility for item in items) <= 0:
            return None
        common_preconditions = set(items[0].preconditions)
        common_actions = set(items[0].recommended_actions)
        common_avoid = set(items[0].avoid_actions)
        for item in items[1:]:
            common_preconditions &= set(item.preconditions)
            common_actions &= set(item.recommended_actions)
            common_avoid &= set(item.avoid_actions)
        if not common_actions:
            return None
        return DistilledProcedure(
            id=str(uuid4()),
            family=items[0].family,
            principle=items[0].principle,
            preconditions=tuple(sorted(common_preconditions)),
            recommended_actions=tuple(sorted(common_actions)),
            avoid_actions=tuple(sorted(common_avoid)),
            source_experience_ids=tuple(item.experience_id for item in items),
            evidence_count=len(items),
            success_count=sum(item.success for item in items),
            failure_count=sum(not item.success for item in items),
            mean_utility=round(mean(item.utility for item in items), 6),
        )

    @staticmethod
    def persist(db: Database, procedure: DistilledProcedure) -> None:
        db.execute(
            "INSERT INTO distilled_procedures (id,family,principle,preconditions_json,recommended_actions_json,avoid_actions_json,source_experience_ids_json,evidence_count,success_count,failure_count,mean_utility,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (
                procedure.id,
                procedure.family,
                procedure.principle,
                db.json(procedure.preconditions),
                db.json(procedure.recommended_actions),
                db.json(procedure.avoid_actions),
                db.json(procedure.source_experience_ids),
                procedure.evidence_count,
                procedure.success_count,
                procedure.failure_count,
                procedure.mean_utility,
            ),
        )
