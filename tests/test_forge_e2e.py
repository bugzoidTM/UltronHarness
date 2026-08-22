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


def test_e2e_runner_fixes_requested_model_on_isolated_gateway_settings(tmp_path: Path) -> None:
    from copy import deepcopy

    from ultron.configuration import Settings, load_settings
    from ultron.research.forge_e2e import ForgeE2ERunner

    original = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    original_primary = original.raw["models"]["primary"]
    runner = ForgeE2ERunner(original, private_root=tmp_path, model_name="ollama_research", seed=123)

    assert original.raw["models"]["primary"] == original_primary
    assert runner.settings.raw["models"]["primary"] == "ollama_research"
    orchestrator = runner._orchestrator(["file.list", "file.read", "python.execute"])
    assert orchestrator.models.primary_name == "ollama_research"
    assert orchestrator.planning_seed == 123
    assert runner.configured_model == "qwen2.5:3b"
