from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

import yaml

PRIMARY = {
    "causal_reasoning",
    "constraint_satisfaction",
    "debugging",
    "planning",
    "scientific_inference",
    "logical_deduction",
    "abductive_reasoning",
    "counterfactual_reasoning",
    "state_recovery",
    "novel_rule_induction",
}
REQUIRED_FILES = {"contracts.json", "evaluator.py", "split_manifest.json", "leakage_policy.json", "tasks.yaml"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def load_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("general_reasoning_private_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("private evaluator import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(root: Path) -> dict[str, object]:
    missing = sorted(REQUIRED_FILES.difference(item.name for item in root.iterdir()))
    if missing:
        raise AssertionError(f"missing_required_files:{missing}")
    contracts = json.loads((root / "contracts.json").read_text(encoding="utf-8"))
    tasks = yaml.safe_load((root / "tasks.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "split_manifest.json").read_text(encoding="utf-8"))
    leakage = json.loads((root / "leakage_policy.json").read_text(encoding="utf-8"))
    if len(tasks) != 280 or len(contracts) != 280:
        raise AssertionError(f"unexpected_task_count:{len(tasks)}:{len(contracts)}")
    ids = [str(task["id"]) for task in tasks]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate_task_id")
    if set(ids) != set(contracts):
        raise AssertionError("task_contract_id_mismatch")
    split_counts = {split: sum(str(task["split"]) == split for task in tasks) for split in ("calibration", "validation", "unseen")}
    if split_counts != {"calibration": 40, "validation": 40, "unseen": 200}:
        raise AssertionError(f"unexpected_split_counts:{split_counts}")
    families = {str(task["family"]) for task in tasks}
    if not PRIMARY.issubset(families):
        raise AssertionError("primary_family_missing")
    for task in tasks:
        contract = contracts[str(task["id"])]
        forbidden = {"expected_files", "private_success_rule", "gold_answer", "reference_patch"}
        if forbidden.intersection(task):
            raise AssertionError(f"private_key_leak_in_task:{task['id']}")
        if contract["task_id"] != task["id"] or contract["split"] != task["split"] or contract["family"] != task["family"]:
            raise AssertionError(f"contract_metadata_mismatch:{task['id']}")
    if manifest["seeds"] != [53, 71, 89, 107] or manifest["primary_pairs"] != 800:
        raise AssertionError("manifest_seed_or_pair_mismatch")
    if leakage["policy_version"] != "gr2-leakage-v1":
        raise AssertionError("leakage_policy_version_mismatch")
    evaluator = load_evaluator(root / "evaluator.py")
    sample_id = next(task_id for task_id, contract in contracts.items() if contract["split"] == "calibration")
    with tempfile.TemporaryDirectory(prefix="general_reasoning_validate_") as tmp:
        workspace = Path(tmp)
        evaluator.prepare(workspace, sample_id, contracts[sample_id])
        before = digest(sorted(path.name for path in workspace.iterdir()))
        result = evaluator.evaluate(workspace, sample_id, contracts[sample_id])
        if result.get("success") is not False:
            raise AssertionError("evaluator_accepts_unmodified_fixture")
        after = digest(sorted(path.name for path in workspace.iterdir()))
        if before != after:
            raise AssertionError("evaluator_mutated_workspace")
        contract = contracts[sample_id]
        for relative, content in contract["expected_files"].items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        passed = evaluator.evaluate(workspace, sample_id, contract)
        if passed.get("success") is not True:
            raise AssertionError("evaluator_rejects_private_expected_state")
    return {
        "root": str(root),
        "required_files": sorted(REQUIRED_FILES),
        "task_count": len(tasks),
        "split_counts": split_counts,
        "family_count": len(families),
        "primary_family_count": len(PRIMARY),
        "seeds": manifest["seeds"],
        "primary_pairs": manifest["primary_pairs"],
        "evaluator_independent_check": True,
        "leakage_policy_version": leakage["policy_version"],
        "status": "ready_for_calibration_only",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
