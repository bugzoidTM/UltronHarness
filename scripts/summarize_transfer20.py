"""Consolida artefatos já produzidos pelo Transfer-20 sem reexecutar o modelo."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from ultron.research.statistics import summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consolida artefatos Transfer-20")
    parser.add_argument("--artifacts", nargs="+", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = [json.loads(path.read_text(encoding="utf-8")) for path in args.artifacts]
    versions = {item["benchmark_version"] for item in results}
    if len(versions) != 1:
        raise ValueError(f"Artefatos de versões distintas: {sorted(versions)}")
    seeds = [int(item["seed"]) for item in results]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Cada seed deve aparecer apenas uma vez")
    family_gains: dict[str, list[float]] = defaultdict(list)
    for item in results:
        for family, gain in item["by_family"].items():
            family_gains[family].append(float(gain))
    report = {
        "benchmark_version": versions.pop(),
        "model": results[0]["model"],
        "seeds": seeds,
        "runs": [
            {
                "run_id": item["run_id"],
                "seed": item["seed"],
                "fresh": item["fresh"],
                "experienced": item["experienced"],
                "transfer_gain": item["transfer_gain"],
                "by_family": item["by_family"],
            }
            for item in results
        ],
        "statistics": {
            "fresh": summarize(float(item["fresh"]) for item in results).model_dump(),
            "experienced": summarize(float(item["experienced"]) for item in results).model_dump(),
            "transfer_gain": summarize(float(item["transfer_gain"]) for item in results).model_dump(),
            "by_family": {
                family: summarize(gains).model_dump() for family, gains in sorted(family_gains.items())
            },
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["statistics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
