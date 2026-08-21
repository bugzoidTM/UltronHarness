"""Composição auditável de contexto para o runtime Hermes.

O construtor não promove experiência por similaridade. Ele usa a classificação
pública da tarefa, avalia candidatos pelo roteador e injeta conteúdo somente quando
a família foi empiricamente marcada como PROMOTABLE. Até existir evidência pareada,
o comportamento seguro é contexto fresco.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultron.cognition.task_signature import TaskSignature, TaskSignatureClassifier
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.learning.negative_transfer import FamilyUtilityState, NegativeTransferFirewall
from ultron.learning.routing_service import ShadowExperienceRoutingService


@dataclass(slots=True)
class ContextBuild:
    """Resultado explicitamente separado entre memória ordinária e experiência roteada."""

    task_signature: TaskSignature
    task_signature_id: str
    routed_procedures: list[str]
    routing_decision_ids: list[str]
    candidate_count: int

    @property
    def injected(self) -> bool:
        return bool(self.routed_procedures)


class ContextBuilder:
    """Integra assinatura, roteamento e experiência no contexto de planejamento."""

    def __init__(self, db: Database, *, max_candidates: int = 5, max_procedures: int = 2):
        self.db = db
        self.max_candidates = max(1, max_candidates)
        self.max_procedures = max(1, max_procedures)
        self.routing = ShadowExperienceRoutingService(db)

    def _experience_signature(self, row: dict[str, Any]) -> ExperienceSignature:
        return ExperienceSignature(
            category=str(row["category"]),
            family=str(row["family"]),
            domain=str(row["domain"]),
            applicable_failure_classes=self._json_list(row.get("failure_classes_json")),
            tool_families=self._json_list(row.get("tool_families_json")),
            abstraction_level=float(row["abstraction_level"]),
            verified=bool(row["verified"]),
            historical_utility=float(row["historical_utility"]),
            sample_count=int(row["sample_count"]),
            source=str(row["source"]),
        )

    @staticmethod
    def _json_list(value: object) -> list[str]:
        if isinstance(value, str):
            import json

            parsed = json.loads(value)
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        return [str(item) for item in value] if isinstance(value, list) else []

    def _candidates(self) -> list[dict[str, Any]]:
        return self.db.all(
            """SELECT e.id AS experience_id,e.strategy,e.result,e.lessons_json,e.quality,
                      es.category,es.family,es.domain,es.failure_classes_json,
                      es.tool_families_json,es.abstraction_level,es.verified,
                      es.historical_utility,es.sample_count,es.source
                 FROM experiences e
                 JOIN experience_signatures es ON es.experience_id=e.id
                WHERE e.success=1 AND es.verified=1
                ORDER BY es.historical_utility DESC,e.quality DESC,e.created_at DESC
                LIMIT ?""",
            (self.max_candidates,),
        )

    def _decision_id(self, task_id: str, experience_id: str) -> str | None:
        row = self.db.one(
            "SELECT id FROM routing_decisions WHERE task_id=? AND experience_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (task_id, experience_id),
        )
        return str(row["id"]) if row else None

    def build(self, task: dict[str, Any]) -> ContextBuild:
        """Avalia candidatos e retorna procedimentos somente após promoção empírica."""
        task_id = str(task["id"])
        signature = TaskSignatureClassifier.classify(task)
        signature_id = TaskSignatureClassifier.persist(self.db, signature, task_id=task_id)
        candidates = self._candidates()
        procedures: list[str] = []
        decision_ids: list[str] = []
        for candidate in candidates:
            experience = self._experience_signature(candidate)
            result = self.routing.evaluate(
                signature,
                str(candidate["experience_id"]),
                experience,
                task_id=task_id,
                active=True,
                require_promotable=True,
            )
            decision_id = self._decision_id(task_id, str(candidate["experience_id"]))
            if decision_id:
                decision_ids.append(decision_id)
            if result.decision.value != "USE" or len(procedures) >= self.max_procedures:
                continue
            lessons = self._json_list(candidate.get("lessons_json"))
            procedure = "; ".join(lessons).strip() or str(candidate["result"]).strip()
            if procedure:
                procedures.append(procedure[:800])
        return ContextBuild(signature, signature_id, procedures, decision_ids, len(candidates))

    def record_outcome(
        self,
        task_id: str,
        context: ContextBuild,
        *,
        success: bool,
        experience_id: str | None = None,
    ) -> None:
        """Fecha telemetria sem declarar causalidade onde não existe contrafactual."""
        score = 1.0 if success else 0.0
        self.db.execute(
            "UPDATE routing_decisions SET observed_score=? WHERE task_id=? AND observed_score IS NULL",
            (score, task_id),
        )
        if experience_id:
            signature = ExperienceSignature(
                category=context.task_signature.category,
                family=context.task_signature.family,
                domain=context.task_signature.domain,
                tool_families=context.task_signature.required_tools,
                abstraction_level=0.8,
                verified=success,
                historical_utility=0.0,
                sample_count=0,
                source="runtime_task_outcome",
            )
            ExperienceSignatureBuilder.persist(self.db, signature, experience_id)
        rows = self.db.all(
            """SELECT DISTINCT rd.task_family,es.family AS experience_family
                 FROM routing_decisions rd
                 LEFT JOIN experience_signatures es ON es.experience_id=rd.experience_id
                WHERE rd.task_id=?""",
            (task_id,),
        )
        pairs = {(str(row["task_family"]), str(row["experience_family"])) for row in rows if row.get("experience_family")}
        pairs.add((context.task_signature.family, context.task_signature.family))
        for task_family, experience_family in pairs:
            NegativeTransferFirewall.recalculate(self.db, task_family, experience_family)

    def family_is_promotable(self, task_family: str, experience_family: str) -> bool:
        row = self.db.one(
            "SELECT state FROM family_utility_map WHERE task_family=? AND experience_family=?",
            (task_family, experience_family),
        )
        return bool(row and row["state"] == FamilyUtilityState.PROMOTABLE.value)
