"""Serviço auditável de roteamento de experiências Hermes.

Por padrão funciona em shadow. Quando chamado pelo runtime com `active=True`, uma
resposta USE ainda exige que o mapa de utilidade da família esteja PROMOTABLE.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ultron.cognition.task_signature import TaskSignature
from ultron.db import Database
from ultron.learning.experience_matcher import ExperienceMatcher
from ultron.learning.experience_router import (
    ExperienceUtilityRouter,
    RoutingDecision,
    RoutingResult,
)
from ultron.learning.experience_signature import ExperienceSignature
from ultron.learning.experience_utility import ExperienceUtilityModel
from ultron.learning.negative_transfer import FamilyUtilityState, NegativeTransferFirewall


class ShadowExperienceRoutingService:
    """Persiste toda decisão USE/ABSTAIN/REJECT antes de qualquer injeção de contexto."""

    def __init__(
        self,
        db: Database,
        matcher: ExperienceMatcher | None = None,
        router: ExperienceUtilityRouter | None = None,
    ):
        self.db = db
        self.matcher = matcher or ExperienceMatcher()
        self.router = router or ExperienceUtilityRouter()
        self.db.initialize()

    def _is_promotable(self, task_family: str, experience_family: str) -> bool:
        row = self.db.one(
            "SELECT state FROM family_utility_map WHERE task_family=? AND experience_family=?",
            (task_family, experience_family),
        )
        return bool(row and row["state"] == FamilyUtilityState.PROMOTABLE.value)

    def evaluate(
        self,
        task: TaskSignature,
        experience_id: str,
        experience: ExperienceSignature,
        task_id: str | None = None,
        *,
        active: bool = False,
        require_promotable: bool = False,
    ) -> RoutingResult:
        match = self.matcher.match(task, experience)
        estimate = ExperienceUtilityModel.estimate(self.db, experience_id, match)
        blocked = NegativeTransferFirewall.is_blocked(self.db, task.family, experience.family)
        result = self.router.decide(task, estimate, blocked=blocked)
        if (
            active
            and require_promotable
            and result.decision == RoutingDecision.USE
            and not self._is_promotable(task.family, experience.family)
        ):
            result = RoutingResult(
                RoutingDecision.ABSTAIN,
                "family_not_empirically_promoted",
                result.expected_utility,
                result.compatibility,
                result.evidence_count,
            )
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
                self.db.json(
                    {
                        "shadow": not active,
                        "active_context": active,
                        "requires_promotable": require_promotable,
                        "evidence_count": result.evidence_count,
                        "classification_source": task.classification_source,
                    }
                ),
                datetime.now(UTC).isoformat(),
            ),
        )
        return result
