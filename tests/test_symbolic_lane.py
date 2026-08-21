from __future__ import annotations

import pytest

from ultron.cognition.symbolic.classifiers import SymbolicIntent, classify
from ultron.cognition.symbolic.facts import Fact, FactStore
from ultron.cognition.symbolic.math import UnsafeExpressionError, evaluate
from ultron.cognition.symbolic.router import SymbolicLane
from ultron.cognition.symbolic.rules import RuleEngine, equality_rule


def test_ast_math_accepts_only_whitelisted_arithmetic() -> None:
    assert evaluate("(2 + 3) * 4 - 1") == 19
    assert evaluate("7 // 2") == 3
    with pytest.raises(UnsafeExpressionError):
        evaluate("__import__('os').system('whoami')")
    with pytest.raises(UnsafeExpressionError):
        evaluate("2 ** 99")


def test_classifier_is_conservative() -> None:
    assert classify("4 * (5 + 1)") is SymbolicIntent.MATH
    assert classify("fact: build.status") is SymbolicIntent.FACT
    assert classify("Explique como depurar um erro de compilação") is SymbolicIntent.UNSUPPORTED


def test_symbolic_lane_is_shadow_by_default_and_collects_offload_metrics() -> None:
    lane = SymbolicLane()
    record = lane.shadow_record("4 * (5 + 1)")
    assert record["route"]["shadow"] is True
    assert record["route"]["handled"] is True
    assert record["route"]["result"] == "24"
    assert record["metrics"]["llm_calls_saved_candidate"] == 1


def test_symbolic_lane_handles_facts_and_explicit_rules() -> None:
    facts = FactStore([Fact("build.status", "green", "test-output")])
    rules = RuleEngine([equality_rule("deploy_allowed", "build.status", "green", "allow", priority=1)])
    lane = SymbolicLane(facts, rules)
    assert lane.route("fact: build.status").result == "green"
    assert lane.route("rule: deploy_allowed").result == "allow"
    assert lane.route("rule: absent_rule").handled is False


def test_symbolic_lane_has_perfect_accuracy_on_its_declared_deterministic_contract() -> None:
    cases = {
        "1+1": "2",
        "8/2": "4.0",
        "3*(4+2)": "18",
        "9%4": "1",
        "2**5": "32",
        "7//3": "2",
        "-3+8": "5",
        "(10-4)*3": "18",
    }
    lane = SymbolicLane()
    correct = sum(lane.route(prompt).result == expected for prompt, expected in cases.items())
    assert correct / len(cases) >= 0.98
