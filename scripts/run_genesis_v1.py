"""Probe bounded do Genesis v1 — Adaptive Cognitive Policy.

A = DIRECT com uma chamada.
B = GENERIC CLOSED LOOP com política fixa e estado acumulativo.
C = SELF-GENERATED ADAPTIVE POLICY com política sintetizada no diagnóstico.
Todas as condições B/C têm no máximo seis decisões cognitivas por tarefa.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner, GenesisTaskResult
from ultron.genesis.schemas import (
    CognitivePolicy,
    CognitivePolicyRule,
    DeductionOutput,
    DeliberationOutput,
    FinalAnswerOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)
from ultron.genesis.synthesizer import AdaptivePolicySynthesizer
from ultron.models.gateway import ModelGateway

PROTOCOL = "genesis-v1-adaptive-policy"
DIAGNOSIS_IDS = ("reasoning_01", "reasoning_02")
HOLDOUT_IDS = ("reasoning_06", "reasoning_07")
TOTAL_BUDGET = 1024
MAX_DECISIONS = 6
MAX_RULES = 8


class FixtureStructuredGateway:
    """Gateway determinístico de mecânica; não é evidência de capacidade."""

    async def structured(self, schema: type[Any], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> Any:
        del messages, model_name, kwargs
        if schema is CognitivePolicy:
            return CognitivePolicy(
                id="CP-FIXTURE",
                rules=[
                    CognitivePolicyRule(conditions=["no_representation"], operator="REPRESENT", priority=0),
                    CognitivePolicyRule(conditions=["no_hypothesis"], operator="HYPOTHESIZE", priority=1),
                    CognitivePolicyRule(conditions=["no_candidate"], operator="DEDUCT", priority=2),
                    CognitivePolicyRule(conditions=["verification_contradicted"], operator="HYPOTHESIZE", priority=3),
                    CognitivePolicyRule(conditions=["verification_uncertain"], operator="DEDUCT", priority=4),
                    CognitivePolicyRule(conditions=["has_candidate"], operator="VERIFY", priority=5),
                ],
                max_decisions=MAX_DECISIONS,
                rationale="Fixture mecânica de política; não representa descoberta do modelo.",
            )
        if schema is RepresentationOutput:
            return RepresentationOutput(entities=["fixture"], facts=["fixture fact"], constraints=["fixture constraint"], unknowns=["fixture unknown"])
        if schema is HypothesisOutput:
            return HypothesisOutput(hypotheses=["fixture hypothesis"], predictions=["fixture prediction"])
        if schema is DeductionOutput:
            return DeductionOutput(conclusion="11")
        if schema is VerificationOutput:
            return VerificationOutput(status="supported", explanation="fixture verification")
        if schema is DeliberationOutput:
            return DeliberationOutput(note="fixture deliberation", candidate_answer="11")
        if schema is FinalAnswerOutput:
            return FinalAnswerOutput(answer="11")
        raise AssertionError(f"fixture_schema_not_supported:{schema}")


def _settings(root: Path, output: Path, model: str) -> Settings:
    base = load_settings(root)
    raw = deepcopy(base.raw)
    raw["genesis"] = {
        **raw.get("genesis", {}),
        "enabled": False,
        "model": model,
        "seed": 42,
        "max_runtime_seconds": 540,
        "max_tokens": TOTAL_BUDGET,
        "max_decisions": MAX_DECISIONS,
        "max_rules": MAX_RULES,
        "feature_flags": {"synthesis": False, "holdout": False, "writeback": False},
    }
    configured = Settings(raw=raw, root_dir=root)
    configured.data_dir = output / "data"
    configured.db_path = configured.data_dir / "ultron.db"
    configured.workspace_root = output / "workspaces"
    configured.artifacts_dir = output / "artifacts"
    configured.backups_dir = output / "backups"
    for directory in (configured.data_dir, configured.workspace_root, configured.artifacts_dir, configured.backups_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return configured


def _fingerprint(task: BenchmarkTask) -> str:
    payload = task.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _record(result: GenesisTaskResult, policy: CognitivePolicy | None) -> dict[str, Any]:
    return {
        "task_id": result.task.id,
        "condition": result.condition,
        "policy_id": policy.id if policy else None,
        "score": result.evaluation.score,
        "success": result.evaluation.success,
        "response": result.execution.response,
        "model": result.manifest.model,
        "seed": result.manifest.seed,
        "config_hash": result.manifest.config_hash,
        "task_fingerprint": _fingerprint(result.task),
        "decision_budget": result.execution.context_metrics.get("decision_budget", 0),
        "decisions": result.vm_execution.decisions if result.vm_execution else 0,
        "model_calls": result.execution.context_metrics.get("model_calls", 0),
        "vm_valid": result.vm_execution is None or result.vm_execution.valid,
        "termination_reason": result.vm_execution.termination_reason if result.vm_execution else None,
        "failure_category": result.execution.failure_category,
        "evidence": list(result.evaluation.evidence),
    }


def _observation(result: GenesisTaskResult) -> dict[str, Any]:
    return {
        "task_id": result.task.id,
        "objective": result.task.objective,
        "response": result.execution.response[:1000],
        "success": result.evaluation.success,
        "score": result.evaluation.score,
        "errors": ["diagnostic failure observed"] if not result.evaluation.success else [],
    }


async def _run_impl(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = _settings(root, output, args.model)
    fixture_gateway = FixtureStructuredGateway() if args.mode == "fixture" else None
    runner = GenesisPublicRunner(settings)
    if fixture_gateway is not None:
        runner.models = fixture_gateway
    tasks = {task.id: task for task in runner.load_tasks()}
    required_ids = DIAGNOSIS_IDS + HOLDOUT_IDS
    if set(tasks) != set(required_ids):
        raise ValueError("genesis_v1_public_task_set_invalid")
    model_name = args.model
    seed = 42
    rows: list[dict[str, Any]] = []
    async with asyncio.timeout(int(settings.raw["genesis"]["max_runtime_seconds"])):
        diagnosis: list[dict[str, Any]] = []
        for task_id in DIAGNOSIS_IDS:
            result = await runner.run_one(
                task=tasks[task_id], condition="direct", run_id="genesis-v1-diagnosis-direct", model_name=model_name,
                seed=seed, max_tokens=TOTAL_BUDGET, decision_budget=1,
            )
            runner.persist_result(result)
            diagnosis.append(_observation(result))
            rows.append(_record(result, None))
        synthesizer = AdaptivePolicySynthesizer(
            fixture_gateway or ModelGateway(settings), model_name=model_name, seed=seed, max_tokens=TOTAL_BUDGET
        )
        policy = await synthesizer.generate(diagnosis, max_decisions=MAX_DECISIONS, max_rules=MAX_RULES)
        for task_id in DIAGNOSIS_IDS:
            result = await runner.run_one(
                task=tasks[task_id], condition="adaptive_policy", run_id="genesis-v1-diagnosis-adaptive",
                model_name=model_name, seed=seed, max_tokens=TOTAL_BUDGET, policy=policy, decision_budget=MAX_DECISIONS,
            )
            runner.persist_result(result)
            rows.append(_record(result, policy))
        holdout_rows: dict[str, list[dict[str, Any]]] = {"A_direct": [], "B_generic_closed_loop": [], "C_adaptive_policy": []}
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id], condition="direct", run_id="genesis-v1-holdout-direct", model_name=model_name,
                seed=seed, max_tokens=TOTAL_BUDGET, decision_budget=1,
            )
            runner.persist_result(result)
            row = _record(result, None)
            holdout_rows["A_direct"].append(row)
            rows.append(row)
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id], condition="generic_closed_loop", run_id="genesis-v1-holdout-generic",
                model_name=model_name, seed=seed, max_tokens=TOTAL_BUDGET, decision_budget=MAX_DECISIONS,
            )
            runner.persist_result(result)
            row = _record(result, None)
            holdout_rows["B_generic_closed_loop"].append(row)
            rows.append(row)
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id], condition="adaptive_policy", run_id="genesis-v1-holdout-adaptive",
                model_name=model_name, seed=seed, max_tokens=TOTAL_BUDGET, policy=policy, decision_budget=MAX_DECISIONS,
            )
            runner.persist_result(result)
            row = _record(result, policy)
            holdout_rows["C_adaptive_policy"].append(row)
            rows.append(row)
    aggregates = {label: round(sum(row["score"] for row in values) / len(values), 6) for label, values in holdout_rows.items()}
    payload = {
        "protocol": PROTOCOL,
        "scientific_use": "development_only" if args.mode == "fixture" else "bounded_exploratory",
        "model": model_name,
        "seed": seed,
        "total_token_budget_per_task": TOTAL_BUDGET,
        "max_decisions_per_task": MAX_DECISIONS,
        "diagnosis_task_ids": list(DIAGNOSIS_IDS),
        "holdout_task_ids": list(HOLDOUT_IDS),
        "policy": policy.model_dump(mode="json"),
        "selected_policy_id": policy.id,
        "diagnosis_observations_sent_to_synthesizer": diagnosis,
        "holdout_sent_to_synthesizer": False,
        "rationale_used_for_execution": False,
        "writeback_performed": False,
        "synthesis_performed": True,
        "conditions": {
            "A_direct": "uma chamada estruturada com budget total 1024",
            "B_generic_closed_loop": "política fixa com estado acumulativo e no máximo seis decisões",
            "C_adaptive_policy": "política autogerada com estado acumulativo e no máximo seis decisões",
        },
        "aggregates": aggregates,
        "delta_C_minus_B": round(aggregates["C_adaptive_policy"] - aggregates["B_generic_closed_loop"], 6),
        "delta_C_minus_A": round(aggregates["C_adaptive_policy"] - aggregates["A_direct"], 6),
        "rows": rows,
    }
    (output / "genesis_v1_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


async def _run(args: argparse.Namespace) -> int:
    try:
        return await _run_impl(args)
    except Exception as exc:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            "protocol": PROTOCOL,
            "scientific_use": "rejected_invalid",
            "model": args.model,
            "seed": 42,
            "total_token_budget_per_task": TOTAL_BUDGET,
            "max_decisions_per_task": MAX_DECISIONS,
            "diagnosis_task_ids": list(DIAGNOSIS_IDS),
            "holdout_task_ids": list(HOLDOUT_IDS),
            "status": "rejected",
            "invalid_reason": f"{type(exc).__name__}:{str(exc)[:1000]}",
            "holdout_sent_to_synthesizer": False,
            "rationale_used_for_execution": False,
            "writeback_performed": False,
            "synthesis_performed": False,
            "rows": [],
        }
        (output / "genesis_v1_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis v1 Adaptive Cognitive Policy bounded probe.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_v1"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
