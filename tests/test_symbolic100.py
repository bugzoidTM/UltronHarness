from ultron.research.symbolic100 import build_cases, run_symbolic100


def test_symbolic100_is_complete_and_safe() -> None:
    assert len(build_cases()) == 100
    result = run_symbolic100()
    assert result.total == 100
    assert result.accuracy >= 0.99
    assert result.false_positive_rate <= 0.01
    assert result.unsafe_executions == 0
    assert result.promotable is True
