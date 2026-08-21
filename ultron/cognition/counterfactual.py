"""Deliberação contrafactual do Athena, limitada a recomendações em shadow mode."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    name: str
    expected_utility: float
    failure_risk: float
    execution_cost: float
    evidence_count: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Estratégia requer nome")
        if self.evidence_count < 0:
            raise ValueError("Quantidade de evidência não pode ser negativa")
        for value in (self.expected_utility, self.failure_risk, self.execution_cost):
            if not 0.0 <= value <= 1.0:
                raise ValueError("Métricas contrafactuais devem estar entre 0 e 1")


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    recommended: str | None
    rankings: tuple[tuple[str, float], ...]
    reason: str
    shadow: bool = True


class CounterfactualDeliberator:
    """Ordena alternativas observadas; nunca envia nem executa a escolha."""

    def __init__(self, minimum_evidence: int = 3):
        self.minimum_evidence = minimum_evidence

    def compare(self, candidates: list[StrategyCandidate]) -> CounterfactualResult:
        eligible = [item for item in candidates if item.evidence_count >= self.minimum_evidence]
        if not eligible:
            return CounterfactualResult(None, (), "evidencia_insuficiente")
        scored = [
            (
                item.name,
                round(item.expected_utility - (0.6 * item.failure_risk) - (0.2 * item.execution_cost), 6),
            )
            for item in eligible
        ]
        rankings = tuple(sorted(scored, key=lambda item: (-item[1], item[0])))
        return CounterfactualResult(rankings[0][0], rankings, "comparacao_empirica_shadow")
