"""Congela o Router Forge e executa Target sem atualizar utilidade ou promoções."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.research.forge_pairs import ForgePairUtilityRunner
from ultron.research.forge_router import ForgeRouterLearning

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
    pairs = ForgePairUtilityRunner(settings, private_root=args.contract_root, model_name=args.model, seed=args.seed)
    experiment = ForgeRouterLearning(pairs)
    snapshot = experiment.freeze()
    result = experiment.evaluate(snapshot, limit=args.limit)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "traces"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
