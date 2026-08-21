"""Camada shadow que avalia experiências sem injetá-las no orquestrador de produção."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ultron.cognition.task_signature import TaskSignature
from ultron.db import Database
from ultron.learning.experience_matcher import ExperienceMatcher
from ultron.learning.experience_router import ExperienceUtilityRouter, RoutingResult
from ultron.learning.experience_signature import ExperienceSignature
from ultron.learning.experience_utility import ExperienceUtilityModel
from ultron.learning.negative_transfer import NegativeTransferFirewall


class ShadowExperienceRoutingService:
    """Produz telemetria USE/ABSTAIN/REJECT; a saída nunca modifica o contexto ativo."""

    def __init__(self, db: Database, matcher: ExperienceMatcher | None = None, router: ExperienceUtilityRouter | None = None):
        self.db = db
        self.matcher = matcher or ExperienceMatcher()
        self.router = router or ExperienceUtilityRouter()
        self.db.initialize()

    def evaluate(self, task: TaskSignature, experience_id: str, experience: ExperienceSignature, task_id: str | None = None) -> RoutingResult:
        match = self.matcher.match(task, experience)
        estimate = ExperienceUtilityModel.estimate(self.db, experience_id, match)
        blocked = NegativeTransferFirewall.is_blocked(self.db, task.family, experience.family)
        result = self.router.decide(task, estimate, blocked=blocked)
        self.db.execute(
            "INSERT INTO routing_decisions (id,task_id,task_family,experience_id,compatibility,expected_utility,decision,reason,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                task_id,
                task.family,
                experience_id,
                result.compatibility,
                result.expected_utility,
                result.decision.value,
                result.reason,
                self.db.json({"shadow": True, "evidence_count": result.evidence_count, "classification_source": task.classification_source}),
                datetime.now(UTC).isoformat(),
            ),
        )
        return result
