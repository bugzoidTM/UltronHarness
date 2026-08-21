"""Executa Calibration do Project Forge sem permitir gravação de utilidade no Target."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.research.forge_pairs import ForgePairUtilityRunner

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--contract-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = load_settings(ROOT)
    runner = ForgePairUtilityRunner(
        settings,
        private_root=args.contract_root,
        model_name=args.model,
        seed=args.seed,
    )
    result = runner.run(limit=args.limit)
    payload = {
        "run_id": result.run_id,
        "dataset_split": result.split,
        "observations": result.observations,
        "mean_delta": result.mean_delta,
        "artifact_dir": str(result.artifact_dir),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
