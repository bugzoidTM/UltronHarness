"""Executa Transfer-20 e Transfer-100 de forma reproduzível, com contratos isolados."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.learning.transfer import TransferExperiment
from ultron.research.statistics import summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa benchmark procedural de transferência")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--benchmark", default="transfer20", choices=["transfer20", "transfer100", "transfer100_v3"])
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--batch-by-family", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--contract-root", type=Path, default=None, help="Obrigatória para Transfer-100 v3; diretório externo com answers.json.")
    return parser.parse_args()


def benchmark_version(args: argparse.Namespace) -> str:
    if args.benchmark == "transfer20":
        return "procedural-v2"
    if args.benchmark == "transfer100_v3":
        return "transfer100-v3-batched-control" if args.batch_by_family else "transfer100-v3-per-task"
    return "transfer100-v2-batched" if args.batch_by_family else "transfer100-v1"


def build_report(args: argparse.Namespace, results: list[dict], status: str) -> dict:
    gains = [float(item["transfer_gain"]) for item in results]
    return {
        "benchmark": args.benchmark,
        "benchmark_version": benchmark_version(args),
        "model": args.model,
        "requested_seeds": args.seeds,
        "completed_seeds": [item["seed"] for item in results],
        "status": status,
        "timeout_seconds": args.timeout_seconds,
        "execution_mode": "batched_by_family" if args.batch_by_family else "per_task",
        "batch_size": args.batch_size if args.batch_by_family else None,
        "contract_root": str(args.contract_root) if args.contract_root else None,
        "results": [{"run_id": item["run_id"], "seed": item["seed"], "fresh": item["fresh"], "experienced": item["experienced"], "transfer_gain": item["transfer_gain"], "by_family": item["by_family"]} for item in results],
        "statistics": {"transfer_gain": summarize(gains).model_dump()},
    }


def write_report(path: Path | None, report: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_many(args: argparse.Namespace) -> list[dict]:
    settings = load_settings()
    settings.raw["models"]["timeout_seconds"] = max(120, args.timeout_seconds)
    results: list[dict] = []
    for seed in args.seeds:
        result = await TransferExperiment(settings, args.model, seed, benchmark_name=args.benchmark, batch_by_family=args.batch_by_family, batch_size=args.batch_size, contract_root=args.contract_root).run_async()
        results.append(result)
        write_report(args.report, build_report(args, results, "running"))
    return results


def main() -> None:
    args = parse_args()
    if args.benchmark == "transfer100_v3":
        if args.contract_root is None or not (args.contract_root / "answers.json").exists():
            raise SystemExit("Transfer-100 v3 requer --contract-root externo contendo answers.json.")
        if len(args.seeds) < 3:
            raise SystemExit("Transfer-100 v3 requer pelo menos três seeds para declarar um gate.")
    results = asyncio.run(run_many(args))
    report = build_report(args, results, "completed")
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
