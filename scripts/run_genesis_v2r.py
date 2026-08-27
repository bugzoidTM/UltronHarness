"""Probe público Genesis v2-R — Executive Validity Closure.

A = DIRECT com uma chamada estruturada.
B = FIXED EXECUTIVE com até quatro chamadas e controlador fixo.
C = ENDOGENOUS EXECUTIVE com até quatro chamadas; cada saída estruturada escolhe
    o próximo operador, sem chamada adicional de roteamento.

O diagnóstico e o holdout são públicos. Nenhum resultado do diagnóstico é usado
para sintetizar uma política, e o probe não faz writeback.
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
    GENESIS_MAX_OPERATORS,
    GENESIS_MAX_PROGRAMS,
    CognitiveProgram,
    CognitiveProgramBatch,
    DeductionOutput,
    DeliberationOutput,
    FinalAnswerOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)

PROTOCOL = "genesis-v2r-executive-validity-closure"
DIAGNOSIS_IDS = ("reasoning_01", "reasoning_02")
HOLDOUT_IDS = ("reasoning_06", "reasoning_07")
TOTAL_BUDGET = 1024
MAX_DECISIONS = 4
CALL_TOKENS = TOTAL_BUDGET // MAX_DECISIONS


class FixtureStructuredGateway:
    """Gateway determinístico somente para testar encadeamento; não é evidência."""

    async def structured(self, schema: type[Any], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> Any:
        del messages, model_name, kwargs
        if schema is CognitiveProgramBatch:
            return CognitiveProgramBatch(
                programs=[
                    CognitiveProgram(
                        id="CP-FIXTURE",
                        operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"],
                        rationale="Fixture histórica; não representa descoberta do modelo.",
                    )
                ]
            )
        if schema is RepresentationOutput:
            return RepresentationOutput(
                entities=["fixture"],
                facts=["fixture fact"],
                constraints=["fixture constraint"],
                unknowns=["fixture unknown"],
                next_operator="HYPOTHESIZE",
            )
        if schema is HypothesisOutput:
            return HypothesisOutput(
                hypotheses=["fixture hypothesis"],
                predictions=["fixture prediction"],
                next_operator="DEDUCT",
            )
        if schema is DeductionOutput:
            return DeductionOutput(conclusion="11", next_operator="VERIFY")
        if schema is VerificationOutput:
            return VerificationOutput(status="supported", explanation="fixture verification", next_operator="VERIFY")
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
        "max_programs": GENESIS_MAX_PROGRAMS,
        "max_operators": GENESIS_MAX_OPERATORS,
        "max_tokens": TOTAL_BUDGET,
        "max_decisions": MAX_DECISIONS,
        "diagnosis_task_ids": list(DIAGNOSIS_IDS),
        "holdout_task_ids": list(HOLDOUT_IDS),
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


def _recovery_metrics(result: GenesisTaskResult) -> tuple[bool, bool]:
    if result.vm_execution is None:
        return False, False
    statuses = [str(entry.get("verification_status", "")) for entry in result.vm_execution.frame.trace]
    attempted = any(status in {"contradicted", "uncertain"} for status in statuses)
    recovered = attempted and result.vm_execution.valid and result.vm_execution.termination_reason == "verification_supported"
    return attempted, recovered


def _record(result: GenesisTaskResult) -> dict[str, Any]:
    attempted, recovered = _recovery_metrics(result)
    vm = result.vm_execution
    return {
        "task_id": result.task.id,
        "condition": result.condition,
        "score": result.evaluation.score,
        "success": result.evaluation.success,
        "response": result.execution.response,
        "model": result.manifest.model,
        "seed": result.manifest.seed,
        "config_hash": result.manifest.config_hash,
        "task_fingerprint": _fingerprint(result.task),
        "decision_budget": result.execution.context_metrics.get("decision_budget", 0),
        "call_tokens": result.execution.context_metrics.get("call_tokens", 0),
        "model_calls": result.execution.context_metrics.get("model_calls", 0),
        "decisions": vm.decisions if vm else 0,
        "vm_steps": vm.steps if vm else 0,
        "vm_valid": vm is None or vm.valid,
        "termination_reason": vm.termination_reason if vm else "direct_call",
        "failure_category": result.execution.failure_category,
        "error": vm.error if vm else None,
        "recovery_attempted": attempted,
        "recovered": recovered,
        "trace": list(vm.frame.trace) if vm else [],
        "evidence": list(result.evaluation.evidence),
    }


def _is_valid(row: dict[str, Any]) -> bool:
    return bool(row["vm_valid"] and row["failure_category"] is None and row["termination_reason"] in {"direct_call", "verification_supported"})


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
        raise ValueError("genesis_v2_public_task_set_invalid")
    model_name = args.model
    seed = 42
    all_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {
        "A_direct": [],
        "B_fixed_executive": [],
        "C_endogenous_executive": [],
    }
    async with asyncio.timeout(int(settings.raw["genesis"]["max_runtime_seconds"])):
        for task_id in DIAGNOSIS_IDS + HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="direct",
                run_id="genesis-v2-direct",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                decision_budget=1,
            )
            runner.persist_result(result)
            row = _record(result)
            grouped["A_direct"].append(row)
            all_rows.append(row)
        for task_id in DIAGNOSIS_IDS + HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="generic_closed_loop_v2r",
                run_id="genesis-v2r-fixed",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                decision_budget=MAX_DECISIONS,
            )
            runner.persist_result(result)
            row = _record(result)
            grouped["B_fixed_executive"].append(row)
            all_rows.append(row)
        for task_id in DIAGNOSIS_IDS + HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="endogenous_executive_v2r",
                run_id="genesis-v2r-endogenous",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                decision_budget=MAX_DECISIONS,
            )
            runner.persist_result(result)
            row = _record(result)
            grouped["C_endogenous_executive"].append(row)
            all_rows.append(row)
    holdout_groups = {
        label: [row for row in rows if row["task_id"] in HOLDOUT_IDS]
        for label, rows in grouped.items()
    }
    aggregates = {
        label: round(sum(row["score"] for row in rows) / len(rows), 6)
        for label, rows in holdout_groups.items()
    }
    valid_conditions = {label: all(_is_valid(row) for row in rows) for label, rows in holdout_groups.items()}
    all_valid = all(valid_conditions.values())
    ecg = round(aggregates["C_endogenous_executive"] - aggregates["B_fixed_executive"], 6) if all_valid else None
    recovery_rows = holdout_groups["C_endogenous_executive"]
    recovery_attempts = sum(int(row["recovery_attempted"]) for row in recovery_rows)
    recovery_successes = sum(int(row["recovered"]) for row in recovery_rows)
    payload = {
        "protocol": PROTOCOL,
        "scientific_use": "development_only" if args.mode == "fixture" else ("bounded_exploratory" if all_valid else "rejected_invalid"),
        "model": model_name,
        "seed": seed,
        "total_token_budget_per_task": TOTAL_BUDGET,
        "max_decisions_per_task": MAX_DECISIONS,
        "call_tokens_fixed_and_endogenous": CALL_TOKENS,
        "diagnosis_task_ids": list(DIAGNOSIS_IDS),
        "holdout_task_ids": list(HOLDOUT_IDS),
        "holdout_sent_to_synthesizer": False,
        "rationale_used_for_execution": False,
        "synthesis_performed": False,
        "writeback_performed": False,
        "conditions": {
            "A_direct": "uma chamada estruturada de até 1024 tokens",
            "B_fixed_executive": "até quatro chamadas de 256 tokens com controlador fixo; next_operator ignorado",
            "C_endogenous_executive": "até quatro chamadas de 256 tokens; cada saída escolhe next_operator sem chamada extra",
        },
        "holdout_validity": valid_conditions,
        "aggregates": aggregates,
        "ecg_C_minus_B": ecg,
        "delta_C_minus_A": round(aggregates["C_endogenous_executive"] - aggregates["A_direct"], 6) if all_valid else None,
        "adaptive_recovery_rate": round(recovery_successes / recovery_attempts, 6) if recovery_attempts else 0.0,
        "adaptive_recovery_attempts": recovery_attempts,
        "adaptive_recovery_successes": recovery_successes,
        "rows": all_rows,
    }
    (output / "genesis_v2r_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all_valid or args.mode == "fixture" else 2


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
            "synthesis_performed": False,
            "writeback_performed": False,
            "rows": [],
        }
        (output / "genesis_v2r_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis v2-R Executive Validity Closure bounded probe.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_v2r"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
