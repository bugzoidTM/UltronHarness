from __future__ import annotations

from ultron.cognition.critic import Evidence
from ultron.cognition.strategy_policy import StrategyObservation, StrategyPolicy
from ultron.research.hermes_shadow import (
    CriticABCase,
    OutcomeObservation,
    PolicyReplayRecord,
    calibrate_world_model,
    evaluate_critic_ab,
    replay_policy,
)


def test_world_calibration_compares_against_majority_baseline() -> None:
    observations = [OutcomeObservation("validation", 0.9, True)] * 3 + [OutcomeObservation("validation", 0.1, False)] * 3
    metrics = calibrate_world_model(observations)
    assert metrics.count == 6
    assert metrics.brier < metrics.baseline_brier
    assert metrics.accuracy == 1.0


def test_critic_ab_measures_false_and_useful_revisions() -> None:
    cases = [
        CriticABCase((Evidence("test_passed", True, "test"),), True),
        CriticABCase((Evidence("test_passed", False, "test"),), False),
    ]
    metrics = evaluate_critic_ab(cases)
    assert metrics.false_revision_rate == 0.0
    assert metrics.useful_revision_rate == 0.5


def test_policy_replay_remains_offline() -> None:
    policy = StrategyPolicy(minimum_observations=3)
    for _ in range(3):
        policy.observe(StrategyObservation("validate", "structured_validation", True, 1.0, 1.0))
    metrics = replay_policy(policy, [PolicyReplayRecord("structured_validation", "validate", "validate")])
    assert metrics.recommendations == 1
    assert metrics.precision == 1.0
