"""Self model empírico baseado em outcomes verificáveis e SQLite canônico."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import sqrt
from uuid import uuid4

from ultron.db import Database

ORIGIN_REPOSITORY = "bugzoidTM/UltronLocal"
ORIGIN_MODULE = "backend/ultronpro/uncertainty.py"


@dataclass(frozen=True)
class CapabilityEstimate:
    domain: str
    task_type: str
    successes: int
    failures: int
    success_rate: float
    calibrated_score: float
    uncertainty: float
    sample_size: int


class EmpiricalSelfModel:
    def __init__(self, db: Database):
        self.db = db

    def observe(self, domain: str, task_type: str, success: bool) -> CapabilityEstimate:
        current = self.db.one("SELECT successes,failures FROM capability_estimates WHERE domain=? AND task_type=?", (domain, task_type)) or {"successes": 0, "failures": 0}
        successes = int(current["successes"]) + int(success)
        failures = int(current["failures"]) + int(not success)
        total = successes + failures
        alpha, beta = 1 + successes, 1 + failures
        mean = alpha / (alpha + beta)
        stddev = sqrt(alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1)))
        estimate = CapabilityEstimate(domain, task_type, successes, failures, round(successes / total, 4), round(max(0.0, mean - stddev), 4), round(min(1.0, 2 * stddev), 4), total)
        self.db.execute("INSERT INTO capability_estimates (id,domain,task_type,successes,failures,success_rate,calibrated_score,uncertainty,sample_size,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(domain,task_type) DO UPDATE SET successes=excluded.successes,failures=excluded.failures,success_rate=excluded.success_rate,calibrated_score=excluded.calibrated_score,uncertainty=excluded.uncertainty,sample_size=excluded.sample_size,updated_at=excluded.updated_at", (str(uuid4()), *asdict(estimate).values(), datetime.now(UTC).isoformat()))
        return estimate

    def estimate(self, domain: str, task_type: str) -> CapabilityEstimate | None:
        row = self.db.one("SELECT domain,task_type,successes,failures,success_rate,calibrated_score,uncertainty,sample_size FROM capability_estimates WHERE domain=? AND task_type=?", (domain, task_type))
        return CapabilityEstimate(**row) if row else None
