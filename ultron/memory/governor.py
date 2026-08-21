"""Governança de writeback baseada em evidência; inspirada conceitualmente no UltronLocal."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ultron.db import Database

ORIGIN_REPOSITORY = "bugzoidTM/UltronLocal"
ORIGIN_MODULE = "backend/ultronpro/memory_governor.py"


@dataclass(frozen=True)
class MemoryWriteDecision:
    should_write: bool
    memory_type: str
    category: str
    confidence: float
    utility_prediction: float
    generalizability: float
    evidence_strength: float
    admission_score: float
    reason: str


class MemoryGovernor:
    """Admite somente experiências verificadas, generalizáveis e potencialmente úteis."""

    def __init__(self, db: Database, threshold: float = 0.60):
        self.db, self.threshold = db, threshold

    def decide(self, *, category: str, verified_success: bool, novel_failure: bool = False,
               successful_recovery: bool = False, generalizable_procedure: bool = False,
               high_evidence_decision: bool = False, confidence: float = 0.5,
               utility_prediction: float = 0.0, generalizability: float = 0.0,
               duplicate_stronger: bool = False, benchmark_private: bool = False,
               task_id: str | None = None) -> MemoryWriteDecision:
        evidence = 1.0 if verified_success or successful_recovery or high_evidence_decision else 0.65 if novel_failure else 0.0
        novelty = 1.0 if novel_failure or successful_recovery else 0.5
        score = 0.30 * evidence + 0.25 * generalizability + 0.20 * novelty + 0.15 * max(0.0, utility_prediction) + 0.10 * confidence
        blocked = benchmark_private or duplicate_stronger or (category == "unknown" and generalizability < 0.6) or evidence == 0.0
        should = not blocked and score >= self.threshold
        reason = "admitted_by_mas" if should else "discarded_private_or_duplicate_or_low_evidence" if blocked else "discarded_below_admission_threshold"
        kind = "procedural" if generalizable_procedure or successful_recovery or novel_failure else "semantic"
        decision = MemoryWriteDecision(should, kind, category, round(confidence, 4), round(utility_prediction, 4), round(generalizability, 4), round(evidence, 4), round(score, 4), reason)
        self.db.execute("INSERT INTO memory_write_decisions (id,task_id,should_write,memory_type,category,confidence,utility_prediction,generalizability,evidence_strength,admission_score,reason,metadata_json,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)", (str(uuid4()), task_id, int(should), kind, category, decision.confidence, decision.utility_prediction, decision.generalizability, decision.evidence_strength, decision.admission_score, reason, datetime.now(UTC).isoformat()))
        return decision

    @staticmethod
    def payload(decision: MemoryWriteDecision) -> dict[str, object]:
        return asdict(decision)
