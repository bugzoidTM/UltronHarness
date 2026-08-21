"""Recovery engine determinístico: classifica evidências e limita tentativas de correção."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    TOOL_ERROR = "TOOL_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MISSING_RESOURCE = "MISSING_RESOURCE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    POLICY_DENIED = "POLICY_DENIED"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    CONTRADICTORY_RESULT = "CONTRADICTORY_RESULT"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class Failure:
    category: FailureCategory
    message: str
    tool: str | None
    recoverable: bool
    attempt: int
    evidence: list[str]


@dataclass(slots=True)
class RecoveryResult:
    strategy: str
    retry: bool
    changed_plan: bool
    confidence: float


class RecoveryEngine:
    """Não replana sem nova evidência classificável; mantém recuperação auditável."""

    recoverable = {
        FailureCategory.TOOL_ERROR,
        FailureCategory.TIMEOUT,
        FailureCategory.INVALID_OUTPUT,
        FailureCategory.MISSING_RESOURCE,
        FailureCategory.VALIDATION_ERROR,
        FailureCategory.DEPENDENCY_ERROR,
        FailureCategory.CONTRADICTORY_RESULT,
    }

    def classify(self, message: str, tool: str | None = None, attempt: int = 1) -> Failure:
        text = message.casefold()
        if "timeout" in text or "tempo máximo" in text:
            category = FailureCategory.TIMEOUT
        elif "json" in text and ("invalid" in text or "invál" in text):
            category = FailureCategory.INVALID_OUTPUT
        elif any(term in text for term in ("not found", "não encontrado", "no such file", "ausente")):
            category = FailureCategory.MISSING_RESOURCE
        elif any(term in text for term in ("permission", "negad", "policy", "bloquead")):
            category = FailureCategory.POLICY_DENIED
        elif any(term in text for term in ("module", "dependency", "biblioteca", "importerror")):
            category = FailureCategory.DEPENDENCY_ERROR
        elif any(term in text for term in ("validation", "schema", "verifica")):
            category = FailureCategory.VALIDATION_ERROR
        elif any(term in text for term in ("contradict", "inconsisten")):
            category = FailureCategory.CONTRADICTORY_RESULT
        elif tool:
            category = FailureCategory.TOOL_ERROR
        else:
            category = FailureCategory.UNKNOWN
        return Failure(category, message, tool, category in self.recoverable, attempt, [message])

    def propose(self, failure: Failure, max_attempts: int = 3) -> RecoveryResult:
        if not failure.recoverable or failure.attempt >= max_attempts:
            return RecoveryResult("encerrar e registrar evidência", False, False, 0.95)
        strategies: dict[FailureCategory, tuple[str, bool]] = {
            FailureCategory.TIMEOUT: ("reduzir escopo ou aplicar timeout maior com nova evidência", True),
            FailureCategory.INVALID_OUTPUT: ("reparar formato e validar schema antes de retentar", True),
            FailureCategory.MISSING_RESOURCE: ("inspecionar recursos disponíveis e selecionar alternativa", True),
            FailureCategory.VALIDATION_ERROR: ("corrigir artefato conforme a condição de sucesso", True),
            FailureCategory.DEPENDENCY_ERROR: ("evitar dependência ausente ou solicitar aprovação para instalação", True),
            FailureCategory.CONTRADICTORY_RESULT: ("coletar evidência adicional e atualizar o plano", True),
            FailureCategory.TOOL_ERROR: ("inspecionar argumentos e tentar ferramenta alternativa", True),
        }
        strategy, changed_plan = strategies.get(failure.category, ("registrar falha não classificada", False))
        return RecoveryResult(strategy, changed_plan, changed_plan, 0.75 if changed_plan else 0.4)

    def metrics(self, failures: list[Failure], recoveries: list[RecoveryResult]) -> dict[str, float]:
        recoverable = sum(item.recoverable for item in failures)
        resolved = sum(item.retry for item in recoveries)
        return {"recovery_rate": round(resolved / recoverable, 4) if recoverable else 0.0}

    @staticmethod
    def persist(db: Any, task_id: str | None, failure: Failure, recovery: RecoveryResult | None = None) -> None:
        from uuid import uuid4

        from ultron.db import Database
        from ultron.memory.service import utcnow

        assert isinstance(db, Database)
        db.execute(
            "INSERT INTO failures (id,task_id,category,message,tool,recoverable,attempt,evidence_json,recovery_json,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()), task_id, failure.category.value, failure.message, failure.tool,
                int(failure.recoverable), failure.attempt, db.json(failure.evidence),
                db.json(asdict(recovery)) if recovery else None, utcnow(),
            ),
        )
