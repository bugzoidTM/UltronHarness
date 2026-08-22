"""Composição auditável de contexto para o runtime Hermes.

O fluxo é assinatura → prefilter → pool diverso → matching → utilidade → injeção.
Experiências só entram no contexto quando o Router emite USE e a família está
empiricamente promovida.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ultron.cognition.task_signature import TaskSignature, TaskSignatureClassifier
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.learning.negative_transfer import FamilyUtilityState, NegativeTransferFirewall
from ultron.learning.routing_service import ShadowExperienceRoutingService
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.schemas import OutcomeResult


@dataclass(slots=True)
class ContextBuild:
    task_signature: TaskSignature
    task_signature_id: str
    routed_procedures: list[str]
    routing_decision_ids: list[str]
    candidate_count: int
    prefilter_count: int = 0

    @property
    def injected(self) -> bool:
        return bool(self.routed_procedures)


class ContextBuilder:
    """Integra assinatura, recuperação de candidatos e roteamento de experiência."""

    def __init__(
        self,
        db: Database,
        *,
        prefilter_limit: int = 50,
        match_limit: int = 10,
        injection_limit: int = 2,
        max_candidates: int | None = None,
        max_procedures: int | None = None,
        minimum_authority: str = "task_registered_verifier",
    ):
        self.db = db
        # Compatibilidade com a superfície Hermes anterior.
        self.prefilter_limit = max(1, max_candidates if max_candidates is not None else prefilter_limit)
        self.match_limit = max(1, match_limit)
        self.injection_limit = max(1, max_procedures if max_procedures is not None else injection_limit)
        self.routing = ShadowExperienceRoutingService(db)
        self.writeback_gate = VerifiedWritebackGate(db, minimum_authority=minimum_authority)

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
            parsed = json.loads(value)
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _procedure_hash(row: dict[str, Any]) -> str:
        text = f"{row.get('lessons_json', '')}|{row.get('result', '')}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _prefilter(self, signature: TaskSignature) -> list[dict[str, Any]]:
        return self.db.all(
            """SELECT e.id AS experience_id,e.strategy,e.result,e.lessons_json,e.quality,
                      es.category,es.family,es.domain,es.failure_classes_json,
                      es.tool_families_json,es.abstraction_level,es.verified,
                      es.historical_utility,es.sample_count,es.source
                 FROM experiences e
                 JOIN experience_signatures es ON es.experience_id=e.id
                WHERE e.success=1 AND e.verification_state='verified' AND e.verified_writeback_id IS NOT NULL
                  AND es.verified=1
                  AND EXISTS (SELECT 1 FROM verified_writebacks vw WHERE vw.id=e.verified_writeback_id AND vw.target_type='experience' AND vw.target_id=e.id AND vw.allowed=1)
                  AND (es.family=? OR es.category=? OR es.domain=?)
                ORDER BY es.historical_utility DESC,e.quality DESC,e.created_at DESC
                LIMIT ?""",
            (signature.family, signature.category, signature.domain, self.prefilter_limit),
        )

    def _diverse_ranked_candidates(self, signature: TaskSignature) -> tuple[list[dict[str, Any]], int]:
        prefetched = self._prefilter(signature)
        unique: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in prefetched:
            key = (str(candidate["family"]), self._procedure_hash(candidate))
            if key not in seen:
                unique.append(candidate)
                seen.add(key)
        ranked = sorted(
            unique,
            key=lambda candidate: self.routing.matcher.match(
                signature, self._experience_signature(candidate)
            ).score,
            reverse=True,
        )
        return ranked[: self.match_limit], len(prefetched)

    def _decision_id(self, task_id: str, experience_id: str) -> str | None:
        row = self.db.one(
            "SELECT id FROM routing_decisions WHERE task_id=? AND experience_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (task_id, experience_id),
        )
        return str(row["id"]) if row else None

    def candidate_recall(self, task: dict[str, Any], relevant_experience_id: str) -> bool:
        """Métrica diagnóstica: candidato útil conhecido entrou no pool pré-filtrado."""
        signature = TaskSignatureClassifier.classify(task)
        return relevant_experience_id in {str(row["experience_id"]) for row in self._prefilter(signature)}

    def build(self, task: dict[str, Any]) -> ContextBuild:
        task_id = str(task["id"])
        signature = TaskSignatureClassifier.classify(task)
        signature_id = TaskSignatureClassifier.persist(self.db, signature, task_id=task_id)
        candidates, prefilter_count = self._diverse_ranked_candidates(signature)
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
            if result.decision.value != "USE" or len(procedures) >= self.injection_limit:
                continue
            lessons = self._json_list(candidate.get("lessons_json"))
            procedure = "; ".join(lessons).strip() or str(candidate["result"]).strip()
            if procedure:
                procedures.append(procedure[:800])
        return ContextBuild(signature, signature_id, procedures, decision_ids, len(candidates), prefilter_count)

    def record_outcome(
        self,
        task_id: str,
        context: ContextBuild,
        *,
        success: bool,
        experience_id: str | None = None,
        outcome_result: OutcomeResult | None = None,
    ) -> None:
        writeback = self.writeback_gate.evaluate(
            task_id=task_id,
            target_type="experience" if experience_id else "routing_context",
            target_id=experience_id,
            outcome_result=outcome_result,
        )
        if not writeback.allowed:
            return
        score = 1.0 if success else 0.0
        self.db.execute(
            "UPDATE routing_decisions SET observed_score=? WHERE task_id=? AND observed_score IS NULL",
            (score, task_id),
        )
        if experience_id:
            self.db.execute(
                "UPDATE experiences SET verification_state='verified', verified_writeback_id=? WHERE id=?",
                (writeback.audit_id, experience_id),
            )
            signature = ExperienceSignature(
                category=context.task_signature.category,
                family=context.task_signature.family,
                domain=context.task_signature.domain,
                tool_families=context.task_signature.required_tools,
                abstraction_level=0.8,
                verified=True,
                historical_utility=0.0,
                sample_count=0,
                source="verified_runtime_outcome",
            )
            ExperienceSignatureBuilder.persist(self.db, signature, experience_id)
        rows = self.db.all(
            """SELECT DISTINCT rd.task_family,es.family AS experience_family
                 FROM routing_decisions rd
                 LEFT JOIN experience_signatures es ON es.experience_id=rd.experience_id
                WHERE rd.task_id=?""",
            (task_id,),
        )
        pairs = {
            (str(row["task_family"]), str(row["experience_family"]))
            for row in rows
            if row.get("experience_family")
        }
        pairs.add((context.task_signature.family, context.task_signature.family))
        for task_family, experience_family in pairs:
            NegativeTransferFirewall.recalculate(self.db, task_family, experience_family)

    def family_is_promotable(self, task_family: str, experience_family: str) -> bool:
        row = self.db.one(
            "SELECT state FROM family_utility_map WHERE task_family=? AND experience_family=?",
            (task_family, experience_family),
        )
        return bool(row and row["state"] == FamilyUtilityState.PROMOTABLE.value)
