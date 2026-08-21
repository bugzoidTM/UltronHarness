"""Executa Transfer-100 v3 em Never/Always/Router e registra controle batched separado."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.learning.transfer import TransferExperiment, TransferRoutingAblation
from ultron.research.statistics import summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ablação Hermes Transfer-100 v3")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--batched-control", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--allow-partial-seeds", action="store_true", help="Permite retomar um subconjunto; o relatório consolidado continua exigindo três seeds.")
    return parser.parse_args()


def compact(result: dict) -> dict:
    return {
        "run_id": result["run_id"],
        "seed": result["seed"],
        "conditions": result["conditions"],
        "transfer_gain_vs_never": result["transfer_gain_vs_never"],
        "abstention_value": result["abstention_value"],
        "harmful_retrieval_rate": result["harmful_retrieval_rate"],
        "by_family": result["by_family"],
    }


def report_for(args: argparse.Namespace, results: list[dict], batched: list[dict], status: str) -> dict:
    condition_series = {
        condition: [float(result["conditions"][condition]) for result in results]
        for condition in ("never_inject", "always_inject", "router_use_abstain_reject")
    }
    return {
        "benchmark": "transfer100_v3",
        "benchmark_version": "transfer100-v3-routing-per-task",
        "execution_mode": "per_task",
        "contract_root": str(args.contract_root),
        "model": args.model,
        "requested_seeds": args.seeds,
        "completed_seeds": [item["seed"] for item in results],
        "status": status,
        "conditions": ["never_inject", "always_inject", "router_use_abstain_reject"],
        "results": [compact(item) for item in results],
        "statistics": {name: summarize(values).model_dump() for name, values in condition_series.items()},
        "statistics_transfer_gain_router": summarize([float(item["transfer_gain_vs_never"]["router_use_abstain_reject"]) for item in results]).model_dump(),
        "statistics_abstention_value": summarize([float(item["abstention_value"]) for item in results]).model_dump(),
        "batched_control": [{"seed": item["seed"], "fresh": item["fresh"], "always": item["experienced"], "transfer_gain": item["transfer_gain"]} for item in batched],
        "interpretation": "O controle batched é diagnóstico de formato e nunca substitui as métricas per-task da ablação Hermes.",
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_many(args: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    settings = load_settings()
    settings.raw["models"]["timeout_seconds"] = max(120, args.timeout_seconds)
    results: list[dict] = []
    batched: list[dict] = []
    for seed in args.seeds:
        result = await TransferRoutingAblation(settings, args.model, seed, contract_root=args.contract_root).run_async()
        results.append(result)
        if args.batched_control:
            control = await TransferExperiment(settings, args.model, seed, benchmark_name="transfer100_v3", contract_root=args.contract_root, batch_by_family=True, batch_size=args.batch_size).run_async()
            batched.append(control)
        write_report(args.report, report_for(args, results, batched, "running"))
    return results, batched


def main() -> None:
    args = parse_args()
    if len(args.seeds) < 3 and not args.allow_partial_seeds:
        raise SystemExit("São necessárias pelo menos três seeds pareadas para declarar um gate Hermes.")
    if not (args.contract_root / "answers.json").exists():
        raise SystemExit("Contrato privado não localizado no diretório externo informado.")
    results, batched = asyncio.run(run_many(args))
    report = report_for(args, results, batched, "completed")
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
