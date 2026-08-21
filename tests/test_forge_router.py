from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import yaml

from ultron.configuration import Settings, load_settings
from ultron.models.gateway import ModelResponse, Usage
from ultron.research.forge_pairs import ForgePairUtilityRunner
from ultron.research.forge_router import ForgeRouterLearning

ROOT = Path(__file__).resolve().parents[1]


def _private_contracts(tmp_path: Path) -> Path:
    root = tmp_path / "private" / "forge_router_v1"
    for split in ("calibration", "target"):
        tasks = yaml.safe_load((ROOT / "benchmarks" / "forge_router_v1" / split / "tasks.yaml").read_text(encoding="utf-8"))
        destination = root / split
        destination.mkdir(parents=True)
        answers = {
            str(task["id"]): {"expected_sequence": ">".join(str(action["code"]) for action in task["actions"][:2])}
            for task in tasks
        }
        (destination / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return root


def test_router_snapshot_is_frozen_and_target_does_not_update_router(tmp_path: Path) -> None:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    pairs = ForgePairUtilityRunner(
        settings,
        public_root=ROOT / "benchmarks" / "forge_router_v1",
        private_root=_private_contracts(tmp_path),
        model_name="local-fallback",
        seed=42,
    )

    async def deterministic(messages, *_args, **_kwargs):
        prompt = messages[-1]["content"]
        codes = [line.split(":", 1)[0] for line in prompt.splitlines() if ": ação autorizada" in line]
        answer = ">".join(codes[:2]) if "Nenhuma experiência" not in prompt else "ZZ"
        return ModelResponse(answer, [], Usage(), 0, "test", "stop", True)

    pairs.models.generate = deterministic
    asyncio.run(pairs.run_calibration(limit=3))
    forge = ForgeRouterLearning(pairs)
    snapshot = forge.freeze()
    state = next(row["state"] for row in snapshot.payload["family_utility_map"] if row["task_family"] == "structured_validation")
    assert state == "PROMOTABLE"
    result = asyncio.run(forge.evaluate_target(snapshot, limit=2))
    assert result["freeze_proof"]["identical"]
    assert result["scores"]["router_use_abstain_reject"] == result["scores"]["always_inject"]
    assert all(trace["decision"] == "USE" for trace in result["traces"]["router_use_abstain_reject"])
    assert pairs.db.one("SELECT COUNT(*) AS count FROM experience_pair_utility WHERE dataset_split='target'")["count"] == 0
