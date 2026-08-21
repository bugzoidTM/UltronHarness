"""Roteador simbólico conservador; por padrão registra, mas não muda a resposta do agente."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ultron.cognition.symbolic.classifiers import SymbolicIntent, classify, query_key
from ultron.cognition.symbolic.facts import FactStore
from ultron.cognition.symbolic.math import UnsafeExpressionError, evaluate
from ultron.cognition.symbolic.rules import RuleEngine


@dataclass(frozen=True, slots=True)
class SymbolicRoute:
    intent: SymbolicIntent
    handled: bool
    result: str | None
    reason: str
    shadow: bool = True


@dataclass(frozen=True, slots=True)
class SymbolicMetrics:
    total: int
    eligible: int
    handled: int
    offload_rate: float
    llm_calls_saved_candidate: int


class SymbolicLane:
    """Executa um subconjunto seguro e registra candidatos a offload.

    ``shadow=True`` é obrigatório como padrão: o resultado é um diagnóstico e
    nunca substitui a decisão do orquestrador até que a acurácia seja validada.
    """

    def __init__(self, facts: FactStore | None = None, rules: RuleEngine | None = None, shadow: bool = True):
        self.facts = facts or FactStore()
        self.rules = rules or RuleEngine([])
        self.shadow = shadow
        self._total = 0
        self._eligible = 0
        self._handled = 0

    def route(self, request: str) -> SymbolicRoute:
        self._total += 1
        intent = classify(request)
        if intent is SymbolicIntent.UNSUPPORTED:
            return SymbolicRoute(intent, False, None, "linguagem_livre_ou_fora_da_whitelist", self.shadow)
        self._eligible += 1
        try:
            if intent is SymbolicIntent.MATH:
                result = str(evaluate(request))
            elif intent is SymbolicIntent.FACT:
                key = query_key(request)
                fact = self.facts.get(key or "")
                if fact is None:
                    return SymbolicRoute(intent, False, None, "fato_ausente", self.shadow)
                result = str(fact.value)
            else:
                key = query_key(request)
                decision = self.rules.evaluate(self.facts)
                if key and not any(key == name.casefold() for name in decision.applied_rules):
                    return SymbolicRoute(intent, False, None, "regra_nao_aplicada", self.shadow)
                if decision.conclusion is None:
                    return SymbolicRoute(intent, False, None, "sem_conclusao_deterministica", self.shadow)
                result = decision.conclusion
        except UnsafeExpressionError as exc:
            return SymbolicRoute(intent, False, None, f"expressao_rejeitada:{exc}", self.shadow)
        self._handled += 1
        return SymbolicRoute(intent, True, result, "resultado_deterministico", self.shadow)

    def metrics(self) -> SymbolicMetrics:
        return SymbolicMetrics(
            total=self._total,
            eligible=self._eligible,
            handled=self._handled,
            offload_rate=round(self._handled / self._total, 6) if self._total else 0.0,
            llm_calls_saved_candidate=self._handled,
        )

    def shadow_record(self, request: str) -> dict[str, Any]:
        """Retorna um registro serializável sem executar qualquer mudança no plano."""
        route = self.route(request)
        return {"route": asdict(route), "metrics": asdict(self.metrics())}
