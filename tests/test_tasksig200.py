from __future__ import annotations

from pathlib import Path

from ultron.research.tasksig_benchmark import evaluate

ROOT = Path(__file__).resolve().parents[1]


def test_tasksig200_closed_set_and_unknown_abstention() -> None:
    result = evaluate(ROOT / "benchmarks" / "tasksig200" / "tasks.yaml")
    assert result.total == 200
    assert result.known_accuracy >= 0.95
    assert result.unknown_recall >= 0.95
    assert result.false_confident_rate < 0.02
    assert result.passed
