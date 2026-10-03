"""Genesis v2-FINAL-OBS — fechamento observável do Executive Control Gate.

O contrato cognitivo é exatamente o da v2-FINAL: B (controlador fixo) e C (executivo
endógeno), as quatro primitivas, 7 decisões × 256 tokens, seed 42, repair_attempts=0 e
os holdouts públicos reasoning_06/reasoning_07. As mensagens enviadas ao modelo são as
mesmas. Esta entrada só acrescenta:

1. observabilidade completa: toda linha serializa candidate_answer (último candidato
   emitido), candidate_history, final_frame_candidate_answer e final_verification_status,
   inclusive após decision_budget_exceeded, erro de schema ou timeout;
2. identidade verificável do modelo (digest, parâmetros e quantização via Ollama), sem
   download automático;
3. separação entre falha cognitiva e falha de infraestrutura (timeout, transporte);
4. persistência incremental: uma interrupção preserva todas as linhas concluídas;
5. gate pré-registrado que separa validade operacional, ECG, ECG-task e ECG-self.

A (DIRECT) é referência secundária executada depois de B/C e nunca entra em ECG.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from scripts.run_genesis_v2final import (
    CALL_TOKENS,
    HOLDOUT_IDS,
    MAX_DECISIONS,
    TOTAL_BUDGET,
    FixtureStructuredGateway,
    _record,
    _settings,
)
from scripts.run_genesis_v2final import PROTOCOL as COGNITIVE_CONTRACT
from ultron.benchmarks.models import BenchmarkTask, TaskExecution
from ultron.genesis.public_runner import GenesisPublicRunner, evaluate_public_task
from ultron.genesis.schemas import CognitiveFrame, RepresentationOutput
from ultron.genesis.vm import CognitiveVM

PROTOCOL = "genesis-v2-final-obs"
SEED = 42
PRIMARY_CONDITIONS = (
    ("B_fixed_executive", "generic_closed_loop_v2final", "genesis-v2final-obs-fixed"),
    ("C_endogenous_executive", "endogenous_executive_v2final", "genesis-v2final-obs-endogenous"),
)
REFERENCE_CONDITION = ("A_direct_reference", "direct", "genesis-v2final-obs-direct")
REFERENCE_CALL_TIMEOUT_SECONDS: float | None = None  # None = timeout da própria tarefa (30 s)
REFERENCE_GLOBAL_TIMEOUT_SECONDS = 540
VALID_TERMINATIONS = {"verification_supported", "direct_call"}
WARMUP_PROBLEM = "Uma estante tem tres prateleiras com livros azuis e verdes. Descreva a estrutura."


class ModelUnavailableError(RuntimeError):
    """O modelo pedido não está instalado; o protocolo proíbe download automático."""


async def model_identity(endpoint: str, tag: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            version = (await client.get(f"{endpoint}/api/version")).json().get("version")
            installed = (await client.get(f"{endpoint}/api/tags")).json().get("models", [])
    except httpx.HTTPError as exc:
        raise ModelUnavailableError(f"runtime_unreachable:{endpoint}:{type(exc).__name__}") from exc
    entry = next((item for item in installed if tag in {item.get("name"), item.get("model")}), None)
    if entry is None:
        names = sorted(str(item.get("name")) for item in installed)
        raise ModelUnavailableError(f"model_not_installed:{tag}; installed={names}")
    details = entry.get("details", {})
    return {
        "tag": tag,
        "digest": entry.get("digest"),
        "size_bytes": entry.get("size"),
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization_level": details.get("quantization_level"),
        "format": details.get("format"),
        "runtime": "ollama",
        "runtime_version": version,
    }


async def warm_up(runner: GenesisPublicRunner, model_name: str) -> dict[str, Any]:
    """Carrega o modelo com um problema neutro fora do protocolo; a saída é descartada.

    Sem isso, o carregamento a frio do modelo consumiria o timeout da primeira linha (B).
    """
    started = perf_counter()
    vm = CognitiveVM(runner.models, model_name=model_name, seed=SEED, max_tokens=CALL_TOKENS)
    try:
        await vm._structured(RepresentationOutput, "Descreva o frame conforme o schema.", CognitiveFrame(problem=WARMUP_PROBLEM))
        error = None
    except Exception as exc:  # o aquecimento nunca é pontuado
        error = type(exc).__name__
    return {"performed": True, "problem": WARMUP_PROBLEM, "output_discarded": True, "error": error, "seconds": round(perf_counter() - started, 3)}


def _external_success(task: BenchmarkTask, candidate: str | None, model: str) -> bool:
    if not candidate:
        return False
    execution = TaskExecution(task_id=task.id, mode="baseline", response=candidate, model=model)
    return evaluate_public_task(task, execution).success


def observable_row(result: Any, label: str) -> dict[str, Any]:
    row = _record(result)
    row["condition_label"] = label
    row["row_status"] = "run"
    row["operationally_valid"] = bool(row["failure_class"] == "none" and row["termination_reason"] in VALID_TERMINATIONS)
    row["candidate_external_success"] = _external_success(result.task, row["candidate_answer"], row["model"])
    row["final_frame_candidate_external_success"] = _external_success(result.task, row["final_frame_candidate_answer"], row["model"])
    return row


def _rate(values: list[bool]) -> float | None:
    return round(sum(int(value) for value in values) / len(values), 6) if values else None


def condition_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    run = [row for row in rows if row.get("row_status") == "run"]
    return {
        "task_ids": [row["task_id"] for row in rows],
        "rows_run": f"{len(run)}/{len(rows)}",
        "operational_validity": f"{sum(int(row['operationally_valid']) for row in run)}/{len(rows)}",
        "protocol_score": _rate([bool(row["success"]) for row in run]) if len(run) == len(rows) else None,
        "candidate_coverage": f"{sum(int(bool(row['candidate_answer'])) for row in run)}/{len(rows)}",
        "external_accuracy_last_candidate": _rate([row["candidate_external_success"] for row in run]) if len(run) == len(rows) else None,
        "external_accuracy_final_frame": _rate([row["final_frame_candidate_external_success"] for row in run]) if len(run) == len(rows) else None,
        "self_termination_rate": _rate([row["termination_reason"] == "verification_supported" and row["final_verification_status"] == "supported" for row in run]) if len(run) == len(rows) else None,
        "recovery_attempts": sum(int(row["recovery_attempted"]) for row in run),
        "recovery_completed": sum(int(row["recovered"]) for row in run),
        "mean_decisions": round(sum(int(row["decisions"]) for row in run) / len(run), 6) if run else None,
        "failure_classes": sorted({row["failure_class"] for row in run}),
    }


def _delta(left: float | None, right: float | None) -> float | None:
    return round(left - right, 6) if left is not None and right is not None else None


def evaluate_gate(primary: dict[str, list[dict[str, Any]]], reference: list[dict[str, Any]]) -> dict[str, Any]:
    """Gate pré-registrado; ver GENESIS_V0_1_PROTOCOL.md, seção v2-FINAL-OBS."""
    b_rows = primary["B_fixed_executive"]
    c_rows = primary["C_endogenous_executive"]
    all_rows = b_rows + c_rows
    expected = len(HOLDOUT_IDS) * len(PRIMARY_CONDITIONS)
    complete = len(all_rows) == expected and all(row.get("row_status") == "run" for row in all_rows)
    infra = (not complete) or any(row["failure_class"] == "infra" for row in all_rows)
    valid_count = sum(int(row.get("operationally_valid", False)) for row in all_rows)
    b_metrics = condition_metrics(b_rows)
    c_metrics = condition_metrics(c_rows)
    a_metrics = condition_metrics(reference) if reference else None
    ecg = None
    if infra:
        gate = "INFRA_INVALID"
    elif valid_count == expected:
        ecg = _delta(c_metrics["protocol_score"], b_metrics["protocol_score"])
        gate = "GO_REPLICATE" if ecg is not None and ecg > 0 else "NO_GO"
    elif valid_count == 0:
        gate = "REJECTED_INVALID_EXECUTION"
    else:
        gate = "PARTIAL_VALIDITY"
    return {
        "gate": gate,
        "operational_validity_BC": f"{valid_count}/{expected}",
        "metrics": {
            "B_fixed_executive": b_metrics,
            "C_endogenous_executive": c_metrics,
            "A_direct_reference": a_metrics,
        },
        "ecg_C_minus_B": ecg,
        "ecg_task_C_minus_B": None if infra else _delta(c_metrics["external_accuracy_last_candidate"], b_metrics["external_accuracy_last_candidate"]),
        "ecg_task_final_frame_C_minus_B": None if infra else _delta(c_metrics["external_accuracy_final_frame"], b_metrics["external_accuracy_final_frame"]),
        "ecg_self_C_minus_B": None if infra else _delta(c_metrics["self_termination_rate"], b_metrics["self_termination_rate"]),
        "delta_task_C_minus_A": _delta(c_metrics["external_accuracy_last_candidate"], a_metrics["external_accuracy_last_candidate"]) if a_metrics and not infra else None,
        "delta_task_B_minus_A": _delta(b_metrics["external_accuracy_last_candidate"], a_metrics["external_accuracy_last_candidate"]) if a_metrics and not infra else None,
    }


def _not_run(label: str, condition: str, task_id: str, reason: str) -> dict[str, Any]:
    return {"task_id": task_id, "condition": condition, "condition_label": label, "row_status": "not_run", "not_run_reason": reason, "failure_class": "infra", "operationally_valid": False}


async def _run_impl(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "genesis_v2final_obs_result.json"
    settings = _settings(root, output, args.model)
    settings.raw["genesis"]["max_runtime_seconds"] = args.global_timeout_seconds
    if args.http_timeout_seconds is not None:
        settings.raw["models"]["timeout_seconds"] = args.http_timeout_seconds
    runner = GenesisPublicRunner(settings)
    registry_entry = settings.raw["models"]["registry"].get(args.model, {})
    if args.mode == "fixture":
        runner.models = FixtureStructuredGateway()
        identity: dict[str, Any] = {"tag": "fixture", "runtime": "fixture"}
        warmup: dict[str, Any] = {"performed": False}
    else:
        if registry_entry.get("provider") != "ollama":
            raise ModelUnavailableError(f"model_must_be_registered_ollama:{args.model}")
        identity = await model_identity(str(registry_entry["endpoint"]).rstrip("/"), str(registry_entry["model"]))
        warmup = await warm_up(runner, args.model)
    tasks = {task.id: task for task in runner.load_tasks()}
    if not set(HOLDOUT_IDS).issubset(tasks):
        raise ValueError("genesis_v2final_obs_public_task_set_invalid")

    primary: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in PRIMARY_CONDITIONS}
    reference: list[dict[str, Any]] = []
    started = perf_counter()
    schedule = [(label, condition, run_id, task_id, primary[label]) for label, condition, run_id in PRIMARY_CONDITIONS for task_id in HOLDOUT_IDS]
    if not args.skip_direct_reference:
        label, condition, run_id = REFERENCE_CONDITION
        schedule += [(label, condition, run_id, task_id, reference) for task_id in HOLDOUT_IDS]

    def payload(status: str) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "cognitive_contract": COGNITIVE_CONTRACT,
            "status": status,
            "mode": args.mode,
            "scientific_use": "development_only" if args.mode == "fixture" else "bounded_exploratory",
            "model": args.model,
            "model_identity": identity,
            "warmup": warmup,
            "seed": SEED,
            "total_token_budget_per_task_BC": TOTAL_BUDGET,
            "max_decisions_per_task": MAX_DECISIONS,
            "call_tokens_fixed_and_endogenous": CALL_TOKENS,
            "direct_reference_max_tokens": TOTAL_BUDGET,
            "repair_attempts": 0,
            "timeouts": {
                "call_timeout_seconds": args.call_timeout_seconds,
                "row_timeout_seconds_BC": (args.call_timeout_seconds or 30) * MAX_DECISIONS,
                "global_soft_deadline_seconds": args.global_timeout_seconds,
                "http_timeout_seconds": settings.raw["models"]["timeout_seconds"],
                "profile": "reference" if args.call_timeout_seconds == REFERENCE_CALL_TIMEOUT_SECONDS and args.global_timeout_seconds == REFERENCE_GLOBAL_TIMEOUT_SECONDS else "declared_hardware_profile",
            },
            "diagnosis_task_ids": [],
            "holdout_task_ids": list(HOLDOUT_IDS),
            "candidate_policy": "candidate_answer = último candidato emitido (DEDUCT ou chamada direta); histórico vazio = nenhum candidato produzido",
            "holdout_sent_to_synthesizer": False,
            "rationale_used_for_execution": False,
            "synthesis_performed": False,
            "writeback_performed": False,
            "automatic_model_download": False,
            "elapsed_seconds": round(perf_counter() - started, 3),
            **evaluate_gate(primary, reference),
            "rows": primary["B_fixed_executive"] + primary["C_endogenous_executive"],
            "reference_rows": reference,
        }

    def persist(status: str) -> dict[str, Any]:
        current = payload(status)
        if args.mode == "fixture":
            current["gate"] = "DEVELOPMENT_ONLY"
        result_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return current

    persist("in_progress")
    for label, condition, run_id, task_id, bucket in schedule:
        if perf_counter() - started > args.global_timeout_seconds:
            bucket.append(_not_run(label, condition, task_id, "global_soft_deadline_exceeded"))
            continue
        result = await runner.run_one(
            task=tasks[task_id],
            condition=condition,
            run_id=run_id,
            model_name=args.model,
            seed=SEED,
            max_tokens=TOTAL_BUDGET,
            decision_budget=1 if condition == "direct" else MAX_DECISIONS,
            call_timeout_seconds=args.call_timeout_seconds,
        )
        runner.persist_result(result)
        bucket.append(observable_row(result, label))
        persist("in_progress")
    final = persist("complete")
    print(json.dumps({key: final[key] for key in ("protocol", "model", "model_identity", "gate", "operational_validity_BC", "ecg_C_minus_B", "ecg_task_C_minus_B", "ecg_self_C_minus_B", "delta_task_C_minus_A", "elapsed_seconds")}, ensure_ascii=False, indent=2))
    return 0 if args.mode == "fixture" or final["gate"] != "INFRA_INVALID" else 2


async def _run(args: argparse.Namespace) -> int:
    try:
        return await _run_impl(args)
    except ModelUnavailableError as exc:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        rejected = {"protocol": PROTOCOL, "status": "rejected", "gate": "MODEL_UNAVAILABLE", "model": args.model, "invalid_reason": str(exc)[:1000], "automatic_model_download": False, "rows": []}
        (output / "genesis_v2final_obs_result.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rejected, ensure_ascii=False, indent=2))
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis v2-FINAL-OBS: mesmo contrato v2-FINAL com observabilidade completa.")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="ollama_research_7b", help="chave do registry em config/default.yaml")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_v2final_obs"))
    parser.add_argument("--call-timeout-seconds", type=float, default=REFERENCE_CALL_TIMEOUT_SECONDS, help="timeout de parede por chamada; igual para A/B/C")
    parser.add_argument("--global-timeout-seconds", type=int, default=REFERENCE_GLOBAL_TIMEOUT_SECONDS, help="deadline suave verificado entre linhas")
    parser.add_argument("--http-timeout-seconds", type=int, default=None, help="timeout HTTP do provider; default do config")
    parser.add_argument("--skip-direct-reference", action="store_true", help="não executa a referência secundária A")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
