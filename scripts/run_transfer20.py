"""Executa uma ou mais seeds do Transfer-20 processual de forma reprodutível."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.learning.transfer import TransferExperiment
from ultron.research.statistics import summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa Transfer-20 processual")
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--benchmark", default="transfer20", choices=["transfer20", "transfer100"])
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--batch-by-family", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    return parser.parse_args()


def build_report(args: argparse.Namespace, results: list[dict], status: str) -> dict:
    gains = [float(item["transfer_gain"]) for item in results]
    return {
        "benchmark": args.benchmark,
        "benchmark_version": "procedural-v2" if args.benchmark == "transfer20" else "transfer100-v2-batched" if args.batch_by_family else "transfer100-v1",
        "model": args.model,
        "requested_seeds": args.seeds,
        "completed_seeds": [item["seed"] for item in results],
        "status": status,
        "timeout_seconds": args.timeout_seconds,
        "execution_mode": "batched_by_family" if args.batch_by_family else "per_task",
        "batch_size": args.batch_size if args.batch_by_family else None,
        "results": [
            {"run_id": item["run_id"], "seed": item["seed"], "fresh": item["fresh"], "experienced": item["experienced"], "transfer_gain": item["transfer_gain"], "by_family": item["by_family"]}
            for item in results
        ],
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
        result = await TransferExperiment(settings, args.model, seed, benchmark_name=args.benchmark, batch_by_family=args.batch_by_family, batch_size=args.batch_size).run_async()
        results.append(result)
        write_report(args.report, build_report(args, results, "running"))
    return results


def main() -> None:
    args = parse_args()
    results = asyncio.run(run_many(args))
    report = build_report(args, results, "completed")
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
