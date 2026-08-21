"""Roteamento seletivo de experiências para Hermes; não ativa injeção de produção por padrão."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ultron.cognition.task_signature import TaskSignature
from ultron.learning.experience_utility import UtilityEstimate


class RoutingDecision(StrEnum):
    USE = "USE"
    ABSTAIN = "ABSTAIN"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class RoutingResult:
    decision: RoutingDecision
    reason: str
    expected_utility: float
    compatibility: float
    evidence_count: int


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    min_classification_confidence: float = 0.70
    min_compatibility: float = 0.55
    min_samples_for_use: int = 3
    use_utility_threshold: float = 0.02
    reject_utility_threshold: float = -0.02


class ExperienceUtilityRouter:
    """No experience é uma decisão explícita e o estado inicial é shadow/experimental."""

    def __init__(self, policy: RouterPolicy | None = None):
        self.policy = policy or RouterPolicy()

    def decide(self, task: TaskSignature, estimate: UtilityEstimate, *, blocked: bool = False) -> RoutingResult:
        confidence = 1.0 - task.uncertainty
        if blocked:
            return RoutingResult(RoutingDecision.REJECT, "negative_transfer_firewall", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        if confidence < self.policy.min_classification_confidence:
            return RoutingResult(RoutingDecision.ABSTAIN, "task_signature_uncertain", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        if estimate.compatibility < self.policy.min_compatibility:
            return RoutingResult(RoutingDecision.REJECT, "incompatible_experience", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        if estimate.sample_count < self.policy.min_samples_for_use:
            return RoutingResult(RoutingDecision.ABSTAIN, "insufficient_paired_evidence", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        if estimate.expected_utility <= self.policy.reject_utility_threshold:
            return RoutingResult(RoutingDecision.REJECT, "negative_expected_utility", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        if estimate.expected_utility >= self.policy.use_utility_threshold:
            return RoutingResult(RoutingDecision.USE, "positive_expected_utility", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
        return RoutingResult(RoutingDecision.ABSTAIN, "utility_near_zero", estimate.expected_utility, estimate.compatibility, estimate.sample_count)
