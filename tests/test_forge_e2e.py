from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_forge_e2e_has_ten_public_missions_without_contracts() -> None:
    root = ROOT / "benchmarks" / "forge_e2e_v1"
    tasks = yaml.safe_load((root / "tasks.yaml").read_text(encoding="utf-8"))
    assert len(tasks) == 10
    assert len({task["id"] for task in tasks}) == 10
    assert all(5 <= task["action_budget"][0] <= task["action_budget"][1] <= 20 for task in tasks)
    assert not any("expected" in task or "oracle" in task for task in tasks)
    assert not (root / "contracts.json").exists()
    assert not (root / "evaluator.py").exists()


def test_e2e_generative_uses_real_planner_and_private_evaluator() -> None:
    source = (ROOT / "ultron" / "research" / "forge_e2e.py").read_text(encoding="utf-8")
    assert "_load_private_evaluator" in source
    assert "private_evaluator_passed" in source
    assert "planner_source" in source
    assert "._make_plan =" not in source
    assert "._execute_plan =" not in source
