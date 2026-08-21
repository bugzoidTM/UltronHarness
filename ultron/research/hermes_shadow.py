"""Avaliações offline dos módulos Athena que permanecem em shadow no Hermes."""

from __future__ import annotations

from dataclasses import dataclass

from ultron.cognition.critic import Evidence, EvidenceCritic
from ultron.cognition.strategy_policy import StrategyPolicy


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    action_family: str
    predicted_success: float
    actual_success: bool


@dataclass(frozen=True, slots=True)
class WorldCalibrationMetrics:
    count: int
    accuracy: float
    brier: float
    baseline_brier: float
    calibration_error: float


def calibrate_world_model(observations: list[OutcomeObservation], bins: int = 5) -> WorldCalibrationMetrics:
    if not observations:
        return WorldCalibrationMetrics(0, 0.0, 0.0, 0.0, 0.0)
    outcomes = [float(item.actual_success) for item in observations]
    majority_probability = sum(outcomes) / len(outcomes)
    accuracy = sum((item.predicted_success >= 0.5) == item.actual_success for item in observations) / len(observations)
    brier = sum((item.predicted_success - float(item.actual_success)) ** 2 for item in observations) / len(observations)
    baseline_brier = sum((majority_probability - outcome) ** 2 for outcome in outcomes) / len(outcomes)
    bucketed: dict[int, list[OutcomeObservation]] = {}
    for item in observations:
        bucket = min(bins - 1, int(item.predicted_success * bins))
        bucketed.setdefault(bucket, []).append(item)
    error = sum(
        len(items) / len(observations) * abs(sum(item.predicted_success for item in items) / len(items) - sum(float(item.actual_success) for item in items) / len(items))
        for items in bucketed.values()
    )
    return WorldCalibrationMetrics(len(observations), round(accuracy, 6), round(brier, 6), round(baseline_brier, 6), round(error, 6))


@dataclass(frozen=True, slots=True)
class CriticABCase:
    evidence: tuple[Evidence, ...]
    result_is_correct: bool


@dataclass(frozen=True, slots=True)
class CriticABMetrics:
    count: int
    false_revision_rate: float
    useful_revision_rate: float
    critic_value: float


def evaluate_critic_ab(cases: list[CriticABCase]) -> CriticABMetrics:
    if not cases:
        return CriticABMetrics(0, 0.0, 0.0, 0.0)
    critic = EvidenceCritic()
    false_revisions = useful_revisions = critic_correct = baseline_correct = 0
    for case in cases:
        result = critic.assess(list(case.evidence))
        would_revise = result.accepted is False
        false_revisions += int(would_revise and case.result_is_correct)
        useful_revisions += int(would_revise and not case.result_is_correct)
        critic_correct += int((result.accepted is not False) == case.result_is_correct)
        baseline_correct += int(case.result_is_correct)
    count = len(cases)
    return CriticABMetrics(count, round(false_revisions / count, 6), round(useful_revisions / count, 6), round((critic_correct - baseline_correct) / count, 6))


@dataclass(frozen=True, slots=True)
class PolicyReplayRecord:
    domain: str
    actual_strategy: str
    best_observed_strategy: str


@dataclass(frozen=True, slots=True)
class PolicyReplayMetrics:
    count: int
    recommendations: int
    precision: float


def replay_policy(policy: StrategyPolicy, records: list[PolicyReplayRecord]) -> PolicyReplayMetrics:
    recommendations = matches = 0
    for record in records:
        recommendation = policy.recommend(record.domain)
        if recommendation.strategy is None:
            continue
        recommendations += 1
        matches += int(recommendation.strategy == record.best_observed_strategy)
    return PolicyReplayMetrics(len(records), recommendations, round(matches / recommendations, 6) if recommendations else 0.0)
