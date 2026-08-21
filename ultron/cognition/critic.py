"""Crítico de evidência do Athena; prioriza verificadores determinísticos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    value: Any
    source: str


@dataclass(frozen=True, slots=True)
class CriticResult:
    accepted: bool | None
    confidence: float
    basis: str
    evidence: tuple[Evidence, ...]
    needs_llm_critic: bool
    shadow: bool = True


class EvidenceCritic:
    """Avalia fatos observáveis, sem inventar avaliação sem um verificador."""

    DETERMINISTIC_KINDS = frozenset({"exit_code", "file_exists", "schema_valid", "test_passed"})

    def assess(self, evidence: list[Evidence]) -> CriticResult:
        deterministic = [item for item in evidence if item.kind in self.DETERMINISTIC_KINDS]
        if not deterministic:
            return CriticResult(
                accepted=None,
                confidence=0.0,
                basis="sem_verificador_deterministico",
                evidence=tuple(evidence),
                needs_llm_critic=True,
            )
        outcomes: list[bool] = []
        for item in deterministic:
            if item.kind == "exit_code":
                outcomes.append(item.value == 0)
            else:
                outcomes.append(bool(item.value))
        accepted = all(outcomes)
        return CriticResult(
            accepted=accepted,
            confidence=1.0,
            basis="evidencia_deterministica",
            evidence=tuple(deterministic),
            needs_llm_critic=False,
        )

    def file_exists(self, path: Path) -> Evidence:
        """Produz evidência local verificável sem seguir links ou executar arquivos."""
        return Evidence("file_exists", path.exists(), str(path))
