"""Fatos explícitos e auditáveis usados pela Symbolic Lane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Fact:
    """Afirmação atômica com uma fonte de evidência local."""

    key: str
    value: Any
    source: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.source.strip():
            raise ValueError("Fato requer chave e proveniência")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confiança do fato deve estar entre 0 e 1")


class FactStore:
    """Armazena fatos locais sem inferir conteúdo não observado."""

    def __init__(self, facts: list[Fact] | None = None):
        self._facts = {fact.key: fact for fact in facts or []}

    def add(self, fact: Fact) -> None:
        self._facts[fact.key] = fact

    def get(self, key: str) -> Fact | None:
        return self._facts.get(key)

    def value(self, key: str, default: Any = None) -> Any:
        fact = self.get(key)
        return fact.value if fact else default

    def snapshot(self) -> list[Fact]:
        return list(self._facts.values())
