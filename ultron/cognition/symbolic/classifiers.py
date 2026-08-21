"""Classificadores conservadores para o caminho simbólico em shadow mode."""

from __future__ import annotations

import re
from enum import StrEnum


class SymbolicIntent(StrEnum):
    MATH = "math"
    FACT = "fact"
    RULE = "rule"
    UNSUPPORTED = "unsupported"


_MATH_ALLOWED = re.compile(r"^[\s\d+\-*/%().]+$")
_FACT_QUERY = re.compile(r"^fact:\s*([a-z][a-z0-9_.-]*)\s*$", re.IGNORECASE)
_RULE_QUERY = re.compile(r"^rule:\s*([a-z][a-z0-9_.-]*)\s*$", re.IGNORECASE)


def classify(text: str) -> SymbolicIntent:
    """Classifica sem adivinhar: qualquer linguagem livre permanece no LLM."""
    candidate = text.strip()
    if candidate and _MATH_ALLOWED.fullmatch(candidate):
        return SymbolicIntent.MATH
    if _FACT_QUERY.fullmatch(candidate):
        return SymbolicIntent.FACT
    if _RULE_QUERY.fullmatch(candidate):
        return SymbolicIntent.RULE
    return SymbolicIntent.UNSUPPORTED


def query_key(text: str) -> str | None:
    """Extrai a chave apenas de formatos de consulta deliberadamente estreitos."""
    match = _FACT_QUERY.fullmatch(text.strip()) or _RULE_QUERY.fullmatch(text.strip())
    return match.group(1).casefold() if match else None
