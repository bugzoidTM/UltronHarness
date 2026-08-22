from __future__ import annotations

from ultron.research.horizon_control import MODES, HorizonControlRunner


def test_horizon_exposes_exactly_three_control_modes() -> None:
    assert MODES == ("full_plan", "short_horizon", "next_action")


def test_horizon_fallback_is_not_counted_as_model_success() -> None:
    summary = HorizonControlRunner._summarize(
        [
            {
                "external_success": True,
                "model_cognitive_success": False,
                "planner_source": "fallback_control",
                "tool_calls": 1,
                "llm_calls": 1,
            },
            {
                "external_success": True,
                "model_cognitive_success": True,
                "planner_source": "model_repaired",
                "tool_calls": 2,
                "llm_calls": 2,
            },
        ]
    )

    assert summary["passed"] == 1
    assert summary["atc"] == 0.5
    assert summary["sdv"] == 0.5


def test_horizon_runner_records_frozen_controls_in_source() -> None:
    source = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath("ultron/research/horizon_control.py").read_text(encoding="utf-8")
    assert "requires_external_outcome=True" in source
    assert "injection_limit = 0" in source
    assert "mission_contract_verified" in source
    assert "model_cognitive_success" in source


def test_second_stop_requires_fresh_external_evaluation() -> None:
    source = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath(
        "ultron/research/horizon_control.py"
    ).read_text(encoding="utf-8")

    assert "while True:" in source
    assert "attempt_number = len(evaluation_attempts) + 1" in source
    assert "workspace_hash = compute_fixture_hash(workspace_path)" in source
    assert "external = evaluator.evaluate(workspace_path, task_id, contracts[task_id])" in source
    assert "outcome = await orchestrator.resolve_external_outcome(created[\"id\"], external)" in source
    assert "external_evaluation_attempts" in source


def test_evaluator_exception_invalidates_measurement_without_reusing_verdict() -> None:
    source = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath(
        "ultron/research/horizon_control.py"
    ).read_text(encoding="utf-8")

    assert "evaluator_error" in source
    assert 'invalidation_reasons.append("external_evaluator_error")' in source
    assert '"evaluation_result": "error"' in source
    assert "evaluation_attempts.append" in source
