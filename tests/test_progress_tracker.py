from __future__ import annotations

from ultron.cognition.progress import ProgressTracker


def test_action_loop_detects_repeated_action_despite_growing_observation_history() -> None:
    tracker = ProgressTracker(stagnation_limit=4, action_loop_limit=3)
    observations: list[str] = []
    results: list[tuple[bool, bool]] = []

    for _ in range(4):
        observations.append("resultado inalterado")
        action_loop, stagnation, _ = tracker.assess(
            tool="python.execute",
            arguments={"code": "a1"},
            observations=observations,
            output="resultado inalterado",
            verification_passed=True,
            subgoal_completed=False,
        )
        results.append((action_loop, stagnation))

    assert len({ProgressTracker.signature("python.execute", {"code": "a1"}, observations[:index]) for index in range(1, 5)}) == 4
    assert results == [(False, False), (False, False), (False, False), (True, False)]


def test_action_loop_counter_resets_when_a_distinct_observation_is_seen() -> None:
    tracker = ProgressTracker(stagnation_limit=4, action_loop_limit=3)
    for output in ("novo", "repetido", "repetido"):
        tracker.assess(
            tool="python.execute",
            arguments={"code": "a1"},
            observations=[output],
            output=output,
            verification_passed=True,
            subgoal_completed=False,
        )

    action_loop, stagnation, signal = tracker.assess(
        tool="python.execute",
        arguments={"code": "a1"},
        observations=["resultado diferente"],
        output="resultado diferente",
        verification_passed=True,
        subgoal_completed=False,
    )

    assert signal.progressed
    assert not action_loop
    assert not stagnation
