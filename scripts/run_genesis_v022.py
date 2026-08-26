"""Probe bounded do Genesis v0.2.2 Non-Solving Cognitive VM.

A = DIRECT com uma chamada e budget total fixo.
B = MATCHED COMPUTE com quatro chamadas genéricas e o mesmo budget total.
C = SELF-GENERATED PROGRAM com quatro chamadas, organizadas pelo programa sintetizado.
A síntese usa somente o diagnóstico público; holdouts não entram no sintetizador.
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
from ultron.genesis.synthesizer import CognitiveProgramSynthesizer
from ultron.models.gateway import ModelGateway

PROTOCOL = "genesis-v0.2.2-non-solving"
DIAGNOSIS_IDS = ("reasoning_01", "reasoning_02")
HOLDOUT_IDS = ("reasoning_06", "reasoning_07")
TOTAL_BUDGET = 1024
CALL_BUDGET = 4


class FixtureStructuredGateway:
    """Gateway determinístico apenas para testar encadeamento e paridade; não é evidência."""

    async def structured(self, schema: type[Any], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> Any:
        del messages, model_name, kwargs
        if schema is CognitiveProgramBatch:
            return CognitiveProgramBatch(
                programs=[
                    CognitiveProgram(
                        id="CP-FIXTURE",
                        operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"],
                        rationale="Fixture mecânica; não representa descoberta do modelo.",
                    )
                ]
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
        "max_programs": GENESIS_MAX_PROGRAMS,
        "max_operators": GENESIS_MAX_OPERATORS,
        "max_tokens": TOTAL_BUDGET,
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


def _record(result: GenesisTaskResult, program_id: str | None) -> dict[str, Any]:
    return {
        "task_id": result.task.id,
        "condition": result.condition,
        "program_id": program_id,
        "score": result.evaluation.score,
        "success": result.evaluation.success,
        "response": result.execution.response,
        "model": result.manifest.model,
        "seed": result.manifest.seed,
        "config_hash": result.manifest.config_hash,
        "task_fingerprint": _fingerprint(result.task),
        "call_budget": result.execution.context_metrics.get("call_budget", 0),
        "call_tokens": result.execution.context_metrics.get("call_tokens", 0),
        "model_calls": result.execution.context_metrics.get("model_calls", 0),
        "vm_steps": result.execution.context_metrics.get("vm_steps", 0),
        "vm_valid": result.vm_execution is None or result.vm_execution.valid,
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


async def _run(args: argparse.Namespace) -> int:
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
        raise ValueError("genesis_v022_public_task_set_invalid")
    model_name = args.model
    seed = 42
    all_rows: list[dict[str, Any]] = []
    async with asyncio.timeout(int(settings.raw["genesis"]["max_runtime_seconds"])):
        diagnosis_direct: list[GenesisTaskResult] = []
        for task_id in DIAGNOSIS_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="direct",
                run_id="genesis-v022-diagnosis-direct",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                call_budget=1,
            )
            diagnosis_direct.append(result)
            runner.persist_result(result)
            all_rows.append(_record(result, None))
        diagnosis = [_observation(result) for result in diagnosis_direct]
        synthesizer = CognitiveProgramSynthesizer(
            fixture_gateway or ModelGateway(settings), model_name=model_name, seed=seed, max_tokens=TOTAL_BUDGET
        )
        batch = await synthesizer.generate(diagnosis, max_programs=GENESIS_MAX_PROGRAMS, max_operators=GENESIS_MAX_OPERATORS)
        programs = list(batch.programs)
        if not 1 <= len(programs) <= GENESIS_MAX_PROGRAMS:
            raise ValueError("genesis_v022_program_count_invalid")
        program_diagnosis: dict[str, list[dict[str, Any]]] = {}
        for program in programs:
            program_rows: list[dict[str, Any]] = []
            for task_id in DIAGNOSIS_IDS:
                result = await runner.run_one(
                    task=tasks[task_id],
                    condition="program",
                    run_id=f"genesis-v022-diagnosis-{program.id}",
                    model_name=model_name,
                    seed=seed,
                    max_tokens=TOTAL_BUDGET,
                    program=program,
                    call_budget=CALL_BUDGET,
                )
                runner.persist_result(result)
                row = _record(result, program.id)
                program_rows.append(row)
                all_rows.append(row)
            program_diagnosis[program.id] = program_rows
        selected = max(
            enumerate(programs),
            key=lambda pair: (
                sum(row["score"] for row in program_diagnosis[pair[1].id]) / len(DIAGNOSIS_IDS),
                -pair[0],
            ),
        )[1]
        holdout_rows: dict[str, list[dict[str, Any]]] = {"A_direct": [], "B_matched_compute": [], "C_program": []}
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="direct",
                run_id="genesis-v022-holdout-direct",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                call_budget=1,
            )
            runner.persist_result(result)
            row = _record(result, None)
            holdout_rows["A_direct"].append(row)
            all_rows.append(row)
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="matched_compute",
                run_id="genesis-v022-holdout-matched",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                call_budget=CALL_BUDGET,
            )
            runner.persist_result(result)
            row = _record(result, None)
            holdout_rows["B_matched_compute"].append(row)
            all_rows.append(row)
        for task_id in HOLDOUT_IDS:
            result = await runner.run_one(
                task=tasks[task_id],
                condition="program",
                run_id="genesis-v022-holdout-program",
                model_name=model_name,
                seed=seed,
                max_tokens=TOTAL_BUDGET,
                program=selected,
                call_budget=CALL_BUDGET,
            )
            runner.persist_result(result)
            row = _record(result, selected.id)
            holdout_rows["C_program"].append(row)
            all_rows.append(row)
    aggregates = {
        label: round(sum(row["score"] for row in rows) / len(rows), 6)
        for label, rows in holdout_rows.items()
    }
    payload = {
        "protocol": PROTOCOL,
        "scientific_use": "development_only" if args.mode == "fixture" else "bounded_exploratory",
        "model": model_name,
        "seed": seed,
        "total_token_budget_per_task": TOTAL_BUDGET,
        "matched_call_budget": CALL_BUDGET,
        "diagnosis_task_ids": list(DIAGNOSIS_IDS),
        "holdout_task_ids": list(HOLDOUT_IDS),
        "programs": [program.model_dump(mode="json") for program in programs],
        "selected_program_id": selected.id,
        "diagnosis_observations_sent_to_synthesizer": diagnosis,
        "holdout_sent_to_synthesizer": False,
        "rationale_used_for_execution": False,
        "writeback_performed": False,
        "synthesis_performed": True,
        "conditions": {
            "A_direct": "uma chamada estruturada, budget total 1024",
            "B_matched_compute": "quatro chamadas genéricas de 256 tokens, sem programa específico",
            "C_program": "quatro chamadas estruturadas de 256 tokens, organizadas pelo programa sintetizado",
        },
        "aggregates": aggregates,
        "delta_C_minus_B": round(aggregates["C_program"] - aggregates["B_matched_compute"], 6),
        "delta_C_minus_A": round(aggregates["C_program"] - aggregates["A_direct"], 6),
        "rows": all_rows,
    }
    (output / "genesis_v022_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis v0.2.2 Non-Solving Cognitive VM bounded probe.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_v022"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
