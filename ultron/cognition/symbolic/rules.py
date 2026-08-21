"""Motor de regras pequenas, explícitas e sem aprendizado implícito."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ultron.cognition.symbolic.facts import FactStore


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    when: Callable[[FactStore], bool]
    conclusion: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class RuleResult:
    conclusion: str | None
    applied_rules: tuple[str, ...]


class RuleEngine:
    """Aplica regras por prioridade e retorna uma conclusão rastreável."""

    def __init__(self, rules: list[Rule]):
        self.rules = tuple(sorted(rules, key=lambda item: (-item.priority, item.name)))

    def evaluate(self, facts: FactStore) -> RuleResult:
        applied = tuple(rule.name for rule in self.rules if rule.when(facts))
        conclusion = next(
            (rule.conclusion for rule in self.rules if rule.name in applied),
            None,
        )
        return RuleResult(conclusion=conclusion, applied_rules=applied)


def equality_rule(name: str, key: str, expected: Any, conclusion: str, priority: int = 0) -> Rule:
    """Constrói uma regra simples que não exige avaliação dinâmica."""
    return Rule(
        name=name,
        when=lambda facts: facts.value(key) == expected,
        conclusion=conclusion,
        priority=priority,
    )
