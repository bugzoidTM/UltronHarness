from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from ultron.configuration import Settings, load_settings
from ultron.models.gateway import ModelResponse, Usage
from ultron.research.forge_pairs import ForgePairUtilityRunner

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)


def _private_contracts(tmp_path: Path) -> Path:
    private = tmp_path / "private" / "forge_router_v1"
    for split in ("calibration", "target"):
        tasks = yaml.safe_load((ROOT / "benchmarks" / "forge_router_v1" / split / "tasks.yaml").read_text(encoding="utf-8"))
        destination = private / split
        destination.mkdir(parents=True)
        answers = {
            str(task["id"]): {"expected_sequence": ">".join(str(item["code"]) for item in task["actions"][:2])}
            for task in tasks
        }
        (destination / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return private


def test_forge_calibration_and_target_are_independent() -> None:
    calibration = yaml.safe_load((ROOT / "benchmarks" / "forge_router_v1" / "calibration" / "tasks.yaml").read_text(encoding="utf-8"))
    target = yaml.safe_load((ROOT / "benchmarks" / "forge_router_v1" / "target" / "tasks.yaml").read_text(encoding="utf-8"))
    assert len(calibration) == len(target) == 100
    assert {task["id"] for task in calibration}.isdisjoint({task["id"] for task in target})
    assert {task["case_key"] for task in calibration}.isdisjoint({task["case_key"] for task in target})
    assert {task["source_domain"] for task in calibration}.isdisjoint({task["source_domain"] for task in target})
    variants = [task["lexical_variant"] for task in target]
    assert variants.count("canonical") == 30
    assert variants.count("paraphrased") == 40
    assert variants.count("adversarial") == 30


def test_calibration_records_contextual_pair_utility_and_never_mutates_target(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runner = ForgePairUtilityRunner(
        settings,
        public_root=ROOT / "benchmarks" / "forge_router_v1",
        private_root=_private_contracts(tmp_path),
        model_name="local-fallback",
        seed=77,
    )

    async def deterministic(messages, *_args, **_kwargs):
        prompt = messages[-1]["content"]
        codes = [line.split(":", 1)[0] for line in prompt.splitlines() if ": ação autorizada" in line]
        answer = ">".join(codes[:2]) if "Nenhuma experiência" not in prompt else "ZZ"
        return ModelResponse(answer, [], Usage(), 0, "test", "stop", True)

    runner.models.generate = deterministic
    result = asyncio.run(runner.run_calibration(limit=2))
    rows = runner.db.all("SELECT task_id,task_family,experience_family,source_domain,target_domain,seed,model_name,prompt_version,dataset_split,paired_delta FROM experience_pair_utility ORDER BY task_id")
    assert result.split == "calibration"
    assert result.observations == 2
    assert len(rows) == 2
    assert all(row["dataset_split"] == "calibration" for row in rows)
    assert all(row["seed"] == 77 and row["model_name"] == "local-fallback" for row in rows)
    assert all(row["paired_delta"] == 1.0 for row in rows)
    with pytest.raises(RuntimeError, match="Target Forge"):
        asyncio.run(runner.run_target())
    assert runner.db.one("SELECT COUNT(*) AS count FROM experience_pair_utility WHERE dataset_split='target'")["count"] == 0
