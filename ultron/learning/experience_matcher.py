"""Compatibilidade estruturada entre TaskSignature e ExperienceSignature."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ultron.cognition.task_signature import TaskSignature
from ultron.learning.experience_signature import ExperienceSignature


@dataclass(frozen=True, slots=True)
class MatcherWeights:
    family: float = 0.30
    category: float = 0.20
    failure_class: float = 0.15
    domain: float = 0.10
    tools: float = 0.10
    historical_utility: float = 0.10
    abstraction: float = 0.05

    def validate(self) -> None:
        if round(sum(asdict(self).values()), 6) != 1.0:
            raise ValueError("Os pesos de compatibilidade devem somar 1.0")


@dataclass(frozen=True, slots=True)
class MatchResult:
    score: float
    signals: dict[str, float]
    reason: str


class ExperienceMatcher:
    def __init__(self, weights: MatcherWeights | None = None):
        self.weights = weights or MatcherWeights()
        self.weights.validate()

    def match(self, task: TaskSignature, experience: ExperienceSignature) -> MatchResult:
        family = 1.0 if task.family == experience.family and task.family != "unknown" else 0.0
        category = 1.0 if task.category == experience.category and task.category != "unknown" else 0.0
        failure = 1.0 if task.failure_class and task.failure_class in experience.applicable_failure_classes else 0.0
        domain = 1.0 if task.domain == experience.domain and task.domain != "unknown" else 0.0
        tool_overlap = set(task.required_tools) & set(experience.tool_families)
        tools = len(tool_overlap) / max(1, len(set(task.required_tools)))
        utility = max(0.0, min(1.0, (experience.historical_utility + 1.0) / 2.0))
        abstraction = experience.abstraction_level if family else experience.abstraction_level * 0.25
        signals = {
            "family": family,
            "category": category,
            "failure_class": failure,
            "domain": domain,
            "tools": tools,
            "historical_utility": utility,
            "abstraction": abstraction,
        }
        score = sum(getattr(self.weights, key) * value for key, value in signals.items())
        reason = "structured_match" if family else "no_family_match"
        return MatchResult(round(score, 6), signals, reason)
