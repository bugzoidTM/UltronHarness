"""Política empírica de estratégia do Athena; recomenda em shadow, nunca atua."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    strategy: str
    domain: str
    success: bool
    utility: float
    confidence: float

    def __post_init__(self) -> None:
        if not self.strategy.strip() or not self.domain.strip():
            raise ValueError("Estratégia e domínio são obrigatórios")
        if not 0.0 <= self.utility <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Utilidade e confiança devem estar entre 0 e 1")


@dataclass(frozen=True, slots=True)
class StrategyRecommendation:
    strategy: str | None
    score: float
    observations: int
    reason: str
    shadow: bool = True


class StrategyPolicy:
    """Seleciona somente entre estratégias observadas e category-compatible."""

    def __init__(self, minimum_observations: int = 3):
        self.minimum_observations = minimum_observations
        self._history: dict[tuple[str, str], list[StrategyObservation]] = defaultdict(list)

    def observe(self, observation: StrategyObservation) -> None:
        self._history[(observation.domain, observation.strategy)].append(observation)

    def recommend(self, domain: str) -> StrategyRecommendation:
        candidates: list[StrategyRecommendation] = []
        for (record_domain, strategy), observations in self._history.items():
            if record_domain != domain or len(observations) < self.minimum_observations:
                continue
            success_rate = sum(item.success for item in observations) / len(observations)
            utility = sum(item.utility for item in observations) / len(observations)
            confidence = sum(item.confidence for item in observations) / len(observations)
            score = round(success_rate * utility * confidence, 6)
            candidates.append(StrategyRecommendation(strategy, score, len(observations), "historico_empirico_shadow"))
        if not candidates:
            return StrategyRecommendation(None, 0.0, 0, "evidencia_insuficiente_ou_incompativel")
        return sorted(candidates, key=lambda item: (-item.score, item.strategy or ""))[0]
