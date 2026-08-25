from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.run_general_reasoning_pair import load_private_inputs, pair_summary, safe_trace_summary


def _write_private_root(root: Path) -> None:
    root.mkdir(parents=True)
    tasks = [
        {
            "id": "task_calibration",
            "family": "family_a",
            "split": "calibration",
            "title": "Calibration",
            "objective": "Read local fixture and write a result.",
            "allowed_tools": ["file.list"],
            "action_budget": [1, 2],
        },
        {
            "id": "task_unseen",
            "family": "family_a",
            "split": "unseen",
            "title": "Unseen",
            "objective": "Read local fixture and write a result.",
            "allowed_tools": ["file.list"],
            "action_budget": [1, 2],
        },
    ]
    (root / "tasks.yaml").write_text(yaml.safe_dump(tasks), encoding="utf-8")
    (root / "contracts.json").write_text(json.dumps({"task_calibration": {}, "task_unseen": {}}), encoding="utf-8")
    (root / "evaluator.py").write_text("def prepare(*args): pass\ndef evaluate(*args): return {'success': False}\n", encoding="utf-8")
    (root / "leakage_policy.json").write_text(json.dumps({"policy_version": "test"}), encoding="utf-8")
    (root / "split_manifest.json").write_text(
        json.dumps(
            {
                "benchmark": "general_reasoning_v1",
                "protocol_version": "test",
                "rotation_id": "test-rotation",
                "primary_families": ["family_a"],
                "reserve_families": [],
                "seeds": [53],
                "model_alias": "ollama",
                "effective_model": "qwen2.5:0.5b",
                "splits": {
                    "calibration": {"count": 1, "task_ids": ["task_calibration"]},
                    "validation": {"count": 0, "task_ids": []},
                    "unseen": {"count": 1, "task_ids": ["task_unseen"]},
                },
            }
        ),
        encoding="utf-8",
    )


def _safe_variant(tmp_path: Path, *, variant: str, success: bool = True) -> dict[str, object]:
    prediction = variant == "gr2_candidate"
    return {
        "artifact_dir": str(tmp_path),
        "artifact_hash": "artifact-hash",
        "variant": variant,
        "benchmark": "general_reasoning_v1",
        "commit": "commit",
        "model_alias": "ollama",
        "effective_model": "qwen2.5:0.5b",
        "seed": 53,
        "task_split": "validation",
        "mode": "full_plan",
        "prediction_before_observation_enabled": prediction,
        "protocol_hash": "protocol",
        "split_manifest_hash": "split",
        "leakage_policy_hash": "leakage",
        "contract_bundle_hash": "contracts",
        "freeze_manifest_hash": "freeze",
        "tasks_path_hash": "tasks",
        "private_evaluator_hash": "evaluator",
        "contract_bundle_hash_runtime": "contracts",
        "mission_contract_hash": "tasks",
        "mission_id": "task_1",
        "experimental_contract_hash": "mission-contract",
        "orientation_observation_hash": "orientation",
        "ref_fixture_hash": "fixture",
        "initial_fixture_hash": "fixture",
        "measurement_valid": success,
        "invalidation_reasons": [] if success else ["leakage_audit_failed"],
        "external_success": success,
        "model_cognitive_success": success,
        "outcome_authority_ok": True,
        "prediction_count": 1 if prediction else 0,
        "observed_prediction_count": 1 if prediction else 0,
        "pending_prediction_count": 0,
        "prediction_integrity_verified": True,
        "prediction_temporality_verified": True,
        "prediction_temporality_violation_count": 0,
        "pre_decision_tool_call_detected": False,
        "model_attribution_verified": True,
        "seed_attribution_verified": True,
        "mission_contract_verified": True,
        "orientation_shared_verified": True,
        "tool_contract_respected": True,
        "action_budget_cap_respected": True,
        "leakage_audit_passed": success,
        "evaluator_error": False,
        "agent_tool_calls": 1,
        "total_tool_calls": 1,
        "llm_calls": 1,
        "duration_ms": 1,
        "false_stops": 0,
        "independent_prediction_label_available": False,
    }


def test_load_private_inputs_selects_only_requested_split(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    _write_private_root(private_root)
    protocol = tmp_path / "protocol.md"
    protocol.write_text("protocol", encoding="utf-8")

    loaded = load_private_inputs(private_root, "calibration", protocol)

    assert [task["id"] for task in loaded["tasks"]] == ["task_calibration"]
    assert loaded["freeze"]["split"] == "calibration"
    assert loaded["freeze"]["freeze_manifest_hash"]


def test_load_private_inputs_rejects_mismatched_split_manifest(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    _write_private_root(private_root)
    (private_root / "split_manifest.json").write_text(
        json.dumps({"benchmark": "wrong", "splits": {}}), encoding="utf-8"
    )
    protocol = tmp_path / "protocol.md"
    protocol.write_text("protocol", encoding="utf-8")

    with pytest.raises(ValueError, match="general_reasoning_v1"):
        load_private_inputs(private_root, "calibration", protocol)


def test_pair_summary_requires_identity_and_marks_mismatch_invalid(tmp_path: Path) -> None:
    control = _safe_variant(tmp_path, variant="gr1_control")
    candidate = _safe_variant(tmp_path, variant="gr2_candidate")
    task = {"id": "task_1", "family": "family_a", "split": "validation"}

    pair = pair_summary(control, candidate, task=task, seed=53, variant_order=["gr2_candidate", "gr1_control"])
    assert pair["pair_measurement_valid"] is True
    assert pair["identity_equal"]["effective_model"] is True
    assert pair["variant_order"] == ["gr2_candidate", "gr1_control"]

    candidate["tasks_path_hash"] = "different"
    invalid = pair_summary(control, candidate, task=task, seed=53, variant_order=["gr1_control", "gr2_candidate"])
    assert invalid["pair_measurement_valid"] is False
    assert "pair:tasks_path_hash_mismatch" in invalid["pair_invalidation_reasons"]


def test_safe_trace_summary_preserves_only_sanitized_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "horizon_control.json"
    artifact.write_text(
        json.dumps(
            {
                "benchmark": "general_reasoning_v1",
                "commit": "commit",
                "model_alias": "ollama",
                "effective_model": "qwen2.5:0.5b",
                "seed": 53,
                "prediction_before_observation_enabled": True,
                "task_split": "validation",
                "protocol_hash": "protocol",
                "split_manifest_hash": "split",
                "leakage_policy_hash": "leakage",
                "contract_bundle_hash": "contracts",
                "freeze_manifest_hash": "freeze",
                "tasks_path_hash": "tasks",
                "modes": ["full_plan"],
                "measurement_valid": True,
                "invalidation_reasons": [],
                "private_evaluator_hash": "evaluator",
                "traces": [
                    {
                        "mission_id": "task_1",
                        "controller_mode": "full_plan",
                        "prediction_before_observation_enabled": True,
                        "prediction_count": 1,
                        "observed_prediction_count": 1,
                        "pending_prediction_count": 0,
                        "prediction_integrity_verified": True,
                        "prediction_temporality_verified": True,
                        "prediction_temporality_violation_count": 0,
                        "external_success": True,
                        "model_cognitive_success": True,
                        "outcome_authority_level": "private_mission_evaluator",
                        "pre_decision_tool_call_detected": False,
                        "model_attribution_verified": True,
                        "seed_attribution_verified": True,
                        "mission_contract_verified": True,
                        "orientation_shared_verified": True,
                        "tool_contract_respected": True,
                        "action_budget_cap_respected": True,
                        "leakage_audit": {"passed": True},
                        "external_evaluator_error": None,
                        "agent_tool_calls": 1,
                        "total_tool_calls": 1,
                        "llm_calls": 1,
                        "duration_ms": 1,
                        "false_stops": 0,
                        "experimental_contract_hash": "mission-contract",
                        "orientation_observation_hash": "orientation",
                        "ref_fixture_hash": "fixture",
                        "initial_fixture_hash": "fixture",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = safe_trace_summary(artifact, "gr2_candidate", "full_plan")

    assert summary["measurement_valid"] is True
    assert summary["leakage_audit_passed"] is True
    assert "predictions" not in summary
    assert "private_success_rule" not in summary
