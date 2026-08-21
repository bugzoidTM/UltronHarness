from __future__ import annotations

from ultron.cognition.counterfactual import CounterfactualDeliberator, StrategyCandidate
from ultron.cognition.strategy_policy import StrategyObservation, StrategyPolicy


def test_counterfactual_deliberator_requires_evidence_and_never_executes() -> None:
    deliberator = CounterfactualDeliberator(minimum_evidence=3)
    insufficient = deliberator.compare([StrategyCandidate("fast", 0.9, 0.1, 0.1, 2)])
    assert insufficient.recommended is None
    result = deliberator.compare(
        [
            StrategyCandidate("safe", 0.8, 0.1, 0.3, 4),
            StrategyCandidate("risky", 0.9, 0.8, 0.1, 4),
        ]
    )
    assert result.recommended == "safe"
    assert result.shadow is True


def test_strategy_policy_recommends_only_from_compatible_empirical_history() -> None:
    policy = StrategyPolicy(minimum_observations=3)
    for _ in range(3):
        policy.observe(StrategyObservation("inspect_then_restore", "dependency", True, 0.9, 0.9))
    for _ in range(3):
        policy.observe(StrategyObservation("guess", "dependency", True, 0.5, 0.4))
    policy.observe(StrategyObservation("other_domain", "recovery", True, 1.0, 1.0))
    recommendation = policy.recommend("dependency")
    assert recommendation.strategy == "inspect_then_restore"
    assert recommendation.shadow is True
    assert policy.recommend("unseen").strategy is None
