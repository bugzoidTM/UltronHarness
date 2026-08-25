from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ultron.configuration import load_settings
from ultron.research.horizon_control import HorizonControlRunner

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("gr1_control", "gr2_candidate")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_commit(root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def utc_collection_id() -> str:
    return datetime.now(UTC).strftime("collection_%Y%m%dT%H%M%SZ")


def write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_private_inputs(private_root: Path, split: str, protocol_path: Path) -> dict[str, Any]:
    required = {
        "contracts": private_root / "contracts.json",
        "evaluator": private_root / "evaluator.py",
        "leakage_policy": private_root / "leakage_policy.json",
        "split_manifest": private_root / "split_manifest.json",
        "tasks": private_root / "tasks.yaml",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Arquivos privados ausentes: {missing}")
    split_manifest = json.loads(required["split_manifest"].read_text(encoding="utf-8"))
    tasks = yaml.safe_load(required["tasks"].read_text(encoding="utf-8")) or []
    if split_manifest.get("benchmark") != "general_reasoning_v1":
        raise ValueError("split_manifest não corresponde a general_reasoning_v1")
    split_entry = split_manifest.get("splits", {}).get(split) or {}
    task_ids = [str(item) for item in split_entry.get("task_ids", [])]
    task_by_id = {str(task.get("id")): task for task in tasks}
    if len(task_by_id) != len(tasks) or any(task_id not in task_by_id for task_id in task_ids):
        raise ValueError("tasks.yaml e split_manifest.json não coincidem")
    selected_tasks = [task_by_id[task_id] for task_id in task_ids]
    freeze_payload = {
        "schema": "general_reasoning_v1_freeze_v2",
        "benchmark": "general_reasoning_v1",
        "protocol_version": split_manifest.get("protocol_version"),
        "rotation_id": split_manifest.get("rotation_id"),
        "split": split,
        "split_count": len(selected_tasks),
        "primary_families": int(len(split_manifest.get("primary_families", []))),
        "reserve_families": int(len(split_manifest.get("reserve_families", []))),
        "seeds": [int(item) for item in split_manifest.get("seeds", [])],
        "model_alias": split_manifest.get("model_alias"),
        "effective_model": split_manifest.get("effective_model"),
        "variants": list(VARIANTS),
        "protocol_hash": sha256_path(protocol_path),
        "contracts_hash": sha256_path(required["contracts"]),
        "evaluator_hash": sha256_path(required["evaluator"]),
        "prediction_labeler_hash": sha256_path(private_root / "prediction_label.py") if (private_root / "prediction_label.py").exists() else None,
        "leakage_policy_hash": sha256_path(required["leakage_policy"]),
        "split_manifest_hash": sha256_path(required["split_manifest"]),
        "tasks_hash": sha256_path(required["tasks"]),
        "runner_source_hash": sha256_path(ROOT / "scripts" / "run_general_reasoning_pair.py"),
        "horizon_runner_source_hash": sha256_path(ROOT / "ultron" / "research" / "horizon_control.py"),
        "commit": git_commit(ROOT),
    }
    freeze_payload["freeze_manifest_hash"] = canonical_hash(freeze_payload)
    return {
        "required": required,
        "split_manifest": split_manifest,
        "tasks": selected_tasks,
        "freeze": freeze_payload,
    }


def safe_trace_summary(artifact_path: Path, expected_variant: str, expected_mode: str) -> dict[str, Any]:
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    expected_prediction = expected_variant == "gr2_candidate"
    traces = [trace for trace in payload.get("traces", []) if trace.get("controller_mode") == expected_mode]
    if len(traces) != 1:
        raise ValueError(f"Artefato {artifact_path} não possui exatamente um trace {expected_mode}")
    trace = traces[0]
    reasons = [str(item) for item in payload.get("invalidation_reasons", [])]
    leakage = trace.get("leakage_audit") or {}
    safe = {
        "artifact_dir": str(artifact_path.parent),
        "artifact_hash": sha256_path(artifact_path),
        "variant": expected_variant,
        "benchmark": payload.get("benchmark"),
        "commit": payload.get("commit"),
        "model_alias": payload.get("model_alias"),
        "effective_model": payload.get("effective_model"),
        "seed": payload.get("seed"),
        "task_split": payload.get("task_split"),
        "mode": expected_mode,
        "prediction_before_observation_enabled": payload.get("prediction_before_observation_enabled"),
        "protocol_hash": payload.get("protocol_hash"),
        "split_manifest_hash": payload.get("split_manifest_hash"),
        "leakage_policy_hash": payload.get("leakage_policy_hash"),
        "contract_bundle_hash": payload.get("contract_bundle_hash"),
        "freeze_manifest_hash": payload.get("freeze_manifest_hash"),
        "tasks_path_hash": payload.get("tasks_path_hash"),
        "private_evaluator_hash": payload.get("private_evaluator_hash"),
        "prediction_labeler_hash": payload.get("prediction_labeler_hash"),
        "contract_bundle_hash_runtime": payload.get("contract_bundle_hash_runtime"),
        "mission_contract_hash": payload.get("mission_contract_hash"),
        "mission_id": trace.get("mission_id"),
        "experimental_contract_hash": trace.get("experimental_contract_hash"),
        "orientation_observation_hash": trace.get("orientation_observation_hash"),
        "ref_fixture_hash": trace.get("ref_fixture_hash"),
        "initial_fixture_hash": trace.get("initial_fixture_hash"),
        "measurement_valid": bool(payload.get("measurement_valid")),
        "invalidation_reasons": reasons,
        "external_success": bool(trace.get("external_success")),
        "model_cognitive_success": bool(trace.get("model_cognitive_success")),
        "outcome_authority_ok": trace.get("outcome_authority_level") == "private_mission_evaluator",
        "prediction_count": int(trace.get("prediction_count", 0)),
        "observed_prediction_count": int(trace.get("observed_prediction_count", 0)),
        "pending_prediction_count": int(trace.get("pending_prediction_count", 0)),
        "prediction_integrity_verified": bool(trace.get("prediction_integrity_verified", expected_prediction is False)),
        "prediction_temporality_verified": bool(trace.get("prediction_temporality_verified", expected_prediction is False)),
        "prediction_temporality_violation_count": int(trace.get("prediction_temporality_violation_count", 0)),
        "pre_decision_tool_call_detected": bool(trace.get("pre_decision_tool_call_detected")),
        "model_attribution_verified": bool(trace.get("model_attribution_verified")),
        "seed_attribution_verified": bool(trace.get("seed_attribution_verified")),
        "mission_contract_verified": bool(trace.get("mission_contract_verified")),
        "orientation_shared_verified": bool(trace.get("orientation_shared_verified")),
        "tool_contract_respected": bool(trace.get("tool_contract_respected")),
        "action_budget_cap_respected": bool(trace.get("action_budget_cap_respected")),
        "leakage_audit_passed": bool(leakage.get("passed")),
        "evaluator_error": bool(trace.get("external_evaluator_error")),
        "agent_tool_calls": int(trace.get("agent_tool_calls", 0)),
        "total_tool_calls": int(trace.get("total_tool_calls", 0)),
        "llm_calls": int(trace.get("llm_calls", 0)),
        "duration_ms": int(trace.get("duration_ms", 0)),
        "false_stops": int(trace.get("false_stops", 0)),
        "independent_prediction_label_available": bool(trace.get("independent_prediction_label_available", False)),
        "independent_prediction_label_count": int(trace.get("independent_prediction_label_count", 0)),
        "independent_prediction_accuracy": trace.get("independent_prediction_accuracy"),
        "prediction_labeler_error": trace.get("prediction_labeler_error"),
    }
    if safe["prediction_before_observation_enabled"] is not expected_prediction:
        safe["measurement_valid"] = False
        safe["invalidation_reasons"] = sorted(set(reasons + ["prediction_flag_mismatch"]))
    return safe


def pair_summary(control: dict[str, Any], candidate: dict[str, Any], *, task: dict[str, Any], seed: int, variant_order: list[str]) -> dict[str, Any]:
    identity_fields = (
        "benchmark",
        "commit",
        "effective_model",
        "seed",
        "task_split",
        "mode",
        "protocol_hash",
        "split_manifest_hash",
        "leakage_policy_hash",
        "contract_bundle_hash",
        "freeze_manifest_hash",
        "tasks_path_hash",
        "private_evaluator_hash",
        "prediction_labeler_hash",
        "contract_bundle_hash_runtime",
        "mission_contract_hash",
        "experimental_contract_hash",
        "orientation_observation_hash",
        "ref_fixture_hash",
        "initial_fixture_hash",
    )
    identity_equal = {field: control.get(field) == candidate.get(field) for field in identity_fields}
    reasons: list[str] = []
    if not control["measurement_valid"]:
        reasons.extend(f"gr1:{reason}" for reason in control["invalidation_reasons"] or ["measurement_invalid"])
    if not candidate["measurement_valid"]:
        reasons.extend(f"gr2:{reason}" for reason in candidate["invalidation_reasons"] or ["measurement_invalid"])
    reasons.extend(f"pair:{field}_mismatch" for field, equal in identity_equal.items() if not equal)
    if control["mission_id"] != candidate["mission_id"] or control["mission_id"] != str(task["id"]):
        reasons.append("pair:mission_id_mismatch")
    if control["pending_prediction_count"] or candidate["pending_prediction_count"]:
        reasons.append("pair:prediction_pending")
    if control["evaluator_error"] or candidate["evaluator_error"]:
        reasons.append("pair:evaluator_error")
    if not control["outcome_authority_ok"] or not candidate["outcome_authority_ok"]:
        reasons.append("pair:outcome_authority_mismatch")
    if not control["leakage_audit_passed"] or not candidate["leakage_audit_passed"]:
        reasons.append("pair:leakage_audit_failed")
    return {
        "pair_id": f"{seed}:{task['id']}:{control['mode']}",
        "task_id": str(task["id"]),
        "family": str(task.get("family", "unknown")),
        "seed": int(seed),
        "split": str(task.get("split")),
        "mode": control["mode"],
        "variant_order": list(variant_order),
        "gr1_external_success": control["external_success"],
        "gr2_external_success": candidate["external_success"],
        "gr1_model_cognitive_success": control["model_cognitive_success"],
        "gr2_model_cognitive_success": candidate["model_cognitive_success"],
        "gr1_prediction_count": control["prediction_count"],
        "gr2_prediction_count": candidate["prediction_count"],
        "gr1_observed_prediction_count": control["observed_prediction_count"],
        "gr2_observed_prediction_count": candidate["observed_prediction_count"],
        "gr1_pending_prediction_count": control["pending_prediction_count"],
        "gr2_pending_prediction_count": candidate["pending_prediction_count"],
        "gr1_agent_tool_calls": control["agent_tool_calls"],
        "gr2_agent_tool_calls": candidate["agent_tool_calls"],
        "gr1_total_tool_calls": control["total_tool_calls"],
        "gr2_total_tool_calls": candidate["total_tool_calls"],
        "gr1_llm_calls": control["llm_calls"],
        "gr2_llm_calls": candidate["llm_calls"],
        "gr1_duration_ms": control["duration_ms"],
        "gr2_duration_ms": candidate["duration_ms"],
        "identity_equal": identity_equal,
        "pair_measurement_valid": not reasons,
        "pair_invalidation_reasons": sorted(set(reasons)),
        "independent_prediction_label_available": bool(candidate.get("independent_prediction_label_available")),
    }


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_checkpoint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"completed_variants": {}, "pairs": {}}


async def run_pair(args: argparse.Namespace) -> None:
    private_root = args.private_root.resolve()
    protocol_path = args.protocol_path.resolve()
    private = load_private_inputs(private_root, args.split, protocol_path)
    freeze = private["freeze"]
    split_manifest = private["split_manifest"]
    settings = load_settings(ROOT)
    if args.model != str(split_manifest.get("model_alias")):
        raise ValueError(f"Modelo alias não coincide com o freeze: esperado {split_manifest.get('model_alias')}")
    configured_model = str(settings.raw["models"]["registry"][args.model].get("model", args.model))
    if configured_model != str(split_manifest.get("effective_model")):
        raise ValueError(f"Modelo efetivo não coincide com o freeze: {configured_model}")
    seeds = [int(item) for item in args.seeds.split(",") if item.strip()]
    allowed_seeds = {int(item) for item in split_manifest.get("seeds", [])}
    if any(seed not in allowed_seeds for seed in seeds):
        raise ValueError("Seed fora do split_manifest privado")
    modes = tuple(item.strip() for item in args.modes.split(",") if item.strip())
    if len(modes) != 1 or modes[0] not in {"full_plan", "short_horizon", "next_action"}:
        raise ValueError("A coleta pareada exige exatamente um modo Horizon válido")
    mode = modes[0]
    tasks = list(private["tasks"])
    if args.limit is not None:
        tasks = tasks[: int(args.limit)]
    if not tasks:
        raise ValueError("Nenhuma missão selecionada para a coleta")
    if args.dry_run:
        print(json.dumps({
            "status": "preflight_ready",
            "benchmark": "general_reasoning_v1",
            "split": args.split,
            "mode": mode,
            "task_count": len(tasks),
            "seed_count": len(seeds),
            "freeze": freeze,
            "model_alias": args.model,
            "effective_model": configured_model,
        }, ensure_ascii=False))
        return

    root_destination = settings.artifacts_dir / "research" / "general_reasoning_v1"
    root_destination.mkdir(parents=True, exist_ok=True)
    if args.resume:
        collection_dir = args.resume.resolve()
        manifest_path = collection_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Diretório de retomada sem manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("freeze_manifest_hash") != freeze["freeze_manifest_hash"]:
            raise ValueError("Freeze da retomada não coincide com os arquivos privados atuais")
        if manifest.get("split") != args.split or manifest.get("mode") != mode:
            raise ValueError("Parâmetros de retomada não coincidem com o manifest")
    else:
        collection_dir = root_destination / utc_collection_id()
        suffix = 0
        while collection_dir.exists():
            suffix += 1
            collection_dir = root_destination / f"{utc_collection_id()}_{suffix:02d}"
        collection_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema": "general_reasoning_v1_pair_collection_v2",
            "benchmark": "general_reasoning_v1",
            "split": args.split,
            "mode": mode,
            "seeds": seeds,
            "task_count": len(tasks),
            "task_ids": [str(task["id"]) for task in tasks],
            "model_alias": args.model,
            "effective_model": configured_model,
            "variants": list(VARIANTS),
            "order_seed": int(args.order_seed),
            "freeze_manifest_hash": freeze["freeze_manifest_hash"],
            "freeze": freeze,
            "status": "running",
            "execution_status": "running",
            "measurement_valid": None,
            "independent_prediction_label_available": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        write_json_atomic(collection_dir / "manifest.json", manifest)
    checkpoint_path = collection_dir / "collection_checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint.get("freeze_manifest_hash") not in (None, freeze["freeze_manifest_hash"]):
        raise ValueError("Checkpoint de retomada não coincide com o freeze")
    checkpoint.setdefault("schema", "general_reasoning_v1_pair_checkpoint_v2")
    checkpoint["freeze_manifest_hash"] = freeze["freeze_manifest_hash"]
    checkpoint["split"] = args.split
    checkpoint["mode"] = mode
    checkpoint.setdefault("completed_variants", {})
    checkpoint.setdefault("pairs", {})
    write_json_atomic(checkpoint_path, checkpoint)

    async def run_variant(task: dict[str, Any], seed: int, variant: str) -> dict[str, Any]:
        prediction_enabled = variant == "gr2_candidate"
        runner = HorizonControlRunner(
            settings,
            public_root=private_root,
            private_root=private_root,
            model_name=args.model,
            seed=seed,
            prediction_before_observation=prediction_enabled,
            tasks_path=private["required"]["tasks"],
            task_split=args.split,
            benchmark_name="general_reasoning_v1",
            task_ids=(str(task["id"]),),
            protocol_hash=freeze["protocol_hash"],
            split_manifest_hash=freeze["split_manifest_hash"],
            leakage_policy_hash=freeze["leakage_policy_hash"],
            contract_bundle_hash=freeze["contracts_hash"],
            freeze_manifest_hash=freeze["freeze_manifest_hash"],
        )
        result = await runner.run_async(limit=1, modes=modes)
        artifact = result.artifact_dir / "horizon_control.json"
        return safe_trace_summary(artifact, variant, mode)

    completed_variants: dict[str, Any] = checkpoint["completed_variants"]
    pairs: dict[str, Any] = checkpoint["pairs"]
    for seed in seeds:
        for task in tasks:
            task_id = str(task["id"])
            pair_key = f"{seed}:{task_id}:{mode}"
            rng = random.Random(f"{args.order_seed}:{seed}:{task_id}")
            variant_order = list(VARIANTS)
            rng.shuffle(variant_order)
            for variant in variant_order:
                variant_key = f"{pair_key}:{variant}"
                if variant_key in completed_variants:
                    continue
                completed_variants[variant_key] = {"status": "running", "task_id": task_id, "seed": seed, "variant": variant}
                write_json_atomic(checkpoint_path, checkpoint)
                completed_variants[variant_key] = await run_variant(task, seed, variant)
                write_json_atomic(checkpoint_path, checkpoint)
            if pair_key not in pairs:
                control = completed_variants.get(f"{pair_key}:gr1_control")
                candidate = completed_variants.get(f"{pair_key}:gr2_candidate")
                if isinstance(control, dict) and isinstance(candidate, dict) and control.get("artifact_dir") and candidate.get("artifact_dir"):
                    pairs[pair_key] = pair_summary(control, candidate, task=task, seed=seed, variant_order=variant_order)
                    write_json_atomic(checkpoint_path, checkpoint)

    pair_rows = [pairs[key] for key in sorted(pairs)]
    complete = len(pair_rows) == len(tasks) * len(seeds)
    valid_pairs = [row for row in pair_rows if row["pair_measurement_valid"]]
    invalid_rows = [row for row in pair_rows if not row["pair_measurement_valid"]]
    trace_index: list[dict[str, Any]] = []
    invalid_traces: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []
    for key, summary in sorted(completed_variants.items()):
        if not isinstance(summary, dict) or not summary.get("artifact_dir"):
            continue
        trace_index.append(
            {
                "variant_key": key,
                "variant": summary.get("variant"),
                "task_id": summary.get("mission_id"),
                "seed": summary.get("seed"),
                "artifact_dir": summary.get("artifact_dir"),
                "artifact_hash": summary.get("artifact_hash"),
                "measurement_valid": summary.get("measurement_valid"),
            }
        )
        leakage_rows.append(
            {
                "variant_key": key,
                "task_id": summary.get("mission_id"),
                "seed": summary.get("seed"),
                "variant": summary.get("variant"),
                "passed": summary.get("leakage_audit_passed"),
            }
        )
        if not summary.get("measurement_valid"):
            invalid_traces.append(
                {
                    "variant_key": key,
                    "task_id": summary.get("mission_id"),
                    "seed": summary.get("seed"),
                    "variant": summary.get("variant"),
                    "artifact_hash": summary.get("artifact_hash"),
                    "invalidation_reasons": summary.get("invalidation_reasons", []),
                }
            )
    append_jsonl(collection_dir / "paired_results.jsonl", pair_rows)
    append_jsonl(collection_dir / "invalid_traces.jsonl", invalid_traces + [
        {
            "pair_id": row["pair_id"],
            "task_id": row["task_id"],
            "seed": row["seed"],
            "variant": "pair",
            "invalidation_reasons": row["pair_invalidation_reasons"],
        }
        for row in invalid_rows
    ])
    append_jsonl(collection_dir / "trace_index.jsonl", trace_index)
    leakage_payload = {
        "schema": "general_reasoning_v1_leakage_audit_v2",
        "benchmark": "general_reasoning_v1",
        "split": args.split,
        "freeze_manifest_hash": freeze["freeze_manifest_hash"],
        "audit_scope": "sanitized_runtime_trace_metadata",
        "passed": all(bool(row["passed"]) for row in leakage_rows) if leakage_rows else False,
        "variant_count": len(leakage_rows),
        "failed_count": sum(not bool(row["passed"]) for row in leakage_rows),
        "rows": leakage_rows,
    }
    write_json_atomic(collection_dir / "leakage_audit.json", leakage_payload)
    manifest.update(
        {
            "status": "complete" if complete else "partial",
            "execution_status": "complete" if complete else "partial",
            "measurement_valid": complete and len(valid_pairs) == len(pair_rows),
            "pair_count": len(pair_rows),
            "valid_pair_count": len(valid_pairs),
            "invalid_pair_count": len(invalid_rows),
            "independent_prediction_label_available": all(bool(row.get("independent_prediction_label_available")) for row in pair_rows) if pair_rows else False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
    )
    write_json_atomic(collection_dir / "manifest.json", manifest)
    collection_manifest = {
        "benchmark": "general_reasoning_v1",
        "split": args.split,
        "seeds": seeds,
        "modes": [mode],
        "limit": args.limit,
        "model_alias": args.model,
        "effective_model": configured_model,
        "variant_order_seed": int(args.order_seed),
        "freeze_manifest_hash": freeze["freeze_manifest_hash"],
        "pair_count": len(pair_rows),
        "valid_pair_count": len(valid_pairs),
        "invalid_pair_count": len(invalid_rows),
        "independent_prediction_label_available": all(bool(row.get("independent_prediction_label_available")) for row in pair_rows) if pair_rows else False,
        "variants": [
            {
                "variant": variant,
                "prediction_before_observation": variant == "gr2_candidate",
                "seed_count": len(seeds),
                "task_count": len(tasks),
                "completed_variant_count": sum(1 for item in completed_variants.values() if isinstance(item, dict) and item.get("variant") == variant and item.get("artifact_dir")),
            }
            for variant in VARIANTS
        ],
        "collection_status": "complete" if complete else "partial",
        "measurement_status": "valid" if complete and len(valid_pairs) == len(pair_rows) else "invalid_or_incomplete",
    }
    write_json_atomic(collection_dir / "collection_manifest.json", collection_manifest)
    print(json.dumps({"collection_dir": str(collection_dir), **collection_manifest}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--protocol-path", type=Path, default=ROOT / "GR2_GENERALIZATION_PROTOCOL.md")
    parser.add_argument("--split", choices=("calibration", "validation", "unseen"), required=True)
    parser.add_argument("--seeds", default="53")
    parser.add_argument("--modes", default="full_plan")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="ollama")
    parser.add_argument("--order-seed", type=int, default=20260825)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(run_pair(parser.parse_args()))


if __name__ == "__main__":
    main()
