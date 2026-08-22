"""Gate auditável para impedir promoção e reutilização sem outcome final autoritativo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.db import Database
from ultron.schemas import OutcomeResult


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class VerifiedWritebackDecision:
    audit_id: str
    allowed: bool
    reason: str
    authority_level: str
    minimum_authority: str


class VerifiedWritebackGate:
    """Autoriza promoção somente depois de outcome final com autoridade suficiente."""

    def __init__(self, db: Database, *, minimum_authority: str = "task_registered_verifier"):
        if minimum_authority not in OutcomeAuthority.levels:
            raise ValueError(f"Autoridade mínima inválida para verified writeback: {minimum_authority}")
        self.db = db
        self.minimum_authority = minimum_authority

    def evaluate(
        self,
        *,
        task_id: str | None,
        target_type: str,
        target_id: str | None,
        outcome_result: OutcomeResult | None,
    ) -> VerifiedWritebackDecision:
        if outcome_result is None:
            allowed, reason, authority_level, evidence_refs = False, "final_outcome_required", "none", []
        elif not outcome_result.final:
            allowed, reason, authority_level, evidence_refs = False, "outcome_not_final", outcome_result.authority_level, outcome_result.evidence_refs
        elif not outcome_result.success:
            allowed, reason, authority_level, evidence_refs = False, "outcome_failed", outcome_result.authority_level, outcome_result.evidence_refs
        elif not OutcomeAuthority.allows_verified_writeback(outcome_result, minimum_level=self.minimum_authority):
            allowed, reason, authority_level, evidence_refs = False, "outcome_authority_insufficient", outcome_result.authority_level, outcome_result.evidence_refs
        else:
            allowed, reason, authority_level, evidence_refs = True, "verified_outcome_authorized", outcome_result.authority_level, outcome_result.evidence_refs
        audit_id = str(uuid4())
        self.db.execute(
            """INSERT INTO verified_writebacks
               (id,task_id,target_type,target_id,outcome_success,outcome_final,authority_level,minimum_authority,allowed,evidence_refs_json,reason,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                audit_id,
                task_id,
                target_type,
                target_id,
                int(bool(outcome_result and outcome_result.success)),
                int(bool(outcome_result and outcome_result.final)),
                authority_level,
                self.minimum_authority,
                int(allowed),
                self.db.json(evidence_refs),
                reason,
                utcnow(),
            ),
        )
        return VerifiedWritebackDecision(audit_id, allowed, reason, authority_level, self.minimum_authority)

    def has_verified_writeback(self, *, target_type: str, target_id: str) -> bool:
        row = self.db.one(
            "SELECT 1 AS allowed FROM verified_writebacks WHERE target_type=? AND target_id=? AND allowed=1 ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (target_type, target_id),
        )
        return bool(row)
