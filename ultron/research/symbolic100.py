"""Benchmark local de 100 casos para a Symbolic Lane em shadow mode."""

from __future__ import annotations

from dataclasses import dataclass

from ultron.cognition.symbolic.facts import Fact, FactStore
from ultron.cognition.symbolic.router import SymbolicLane
from ultron.cognition.symbolic.rules import RuleEngine, equality_rule


@dataclass(frozen=True, slots=True)
class SymbolicCase:
    group: str
    request: str
    expected: str | None
    should_handle: bool


@dataclass(frozen=True, slots=True)
class Symbolic100Result:
    total: int
    correct: int
    accuracy: float
    false_positive_routes: int
    false_positive_rate: float
    unsafe_executions: int
    promotable: bool


def build_cases() -> tuple[SymbolicCase, ...]:
    cases: list[SymbolicCase] = []
    for value in range(1, 31):
        cases.append(SymbolicCase("arithmetic", f"{value}+{value * 2}", str(value * 3), True))
    for value in range(1, 21):
        cases.append(SymbolicCase("boolean_rules", f"rule: rule_{value}", "allow" if value % 2 else "deny", True))
    for value in range(1, 21):
        cases.append(SymbolicCase("schema_state_checks", f"fact: schema_{value}", str(value % 2 == 0), True))
    for value in range(1, 16):
        cases.append(SymbolicCase("filesystem_reasoning", f"fact: file_{value}", str(value % 2 == 1), True))
    for value in range(1, 16):
        cases.append(SymbolicCase("simple_deterministic", f"fact: flag_{value}", str(value % 3 == 0), True))
    if len(cases) != 100:
        raise RuntimeError("Symbolic-100 deve ter exatamente 100 casos")
    return tuple(cases)


def run_symbolic100() -> Symbolic100Result:
    facts = []
    rules = []
    for value in range(1, 21):
        facts.append(Fact(f"rule_flag_{value}", value % 2 == 1, "symbolic100"))
        rules.append(equality_rule(f"rule_{value}", f"rule_flag_{value}", value % 2 == 1, "allow" if value % 2 else "deny"))
        facts.append(Fact(f"schema_{value}", value % 2 == 0, "symbolic100"))
    for value in range(1, 16):
        facts.append(Fact(f"file_{value}", value % 2 == 1, "symbolic100"))
        facts.append(Fact(f"flag_{value}", value % 3 == 0, "symbolic100"))
    facts_store = FactStore(facts)
    lane = SymbolicLane(facts_store, RuleEngine(rules), shadow=True)
    rule_index = {rule.name: rule for rule in rules}
    correct = false_positive = unsafe = 0
    for case in build_cases():
        case_lane = lane
        if case.group == "boolean_rules":
            rule_name = case.request.split(":", 1)[1].strip()
            case_lane = SymbolicLane(facts_store, RuleEngine([rule_index[rule_name]]), shadow=True)
        route = case_lane.route(case.request)
        correct += int(route.handled == case.should_handle and route.result == case.expected)
        false_positive += int(not case.should_handle and route.handled)
        unsafe += int(not route.shadow)
    total = 100
    accuracy = correct / total
    false_positive_rate = false_positive / total
    return Symbolic100Result(total, correct, round(accuracy, 6), false_positive, round(false_positive_rate, 6), unsafe, accuracy >= 0.99 and false_positive_rate <= 0.01 and unsafe == 0)
