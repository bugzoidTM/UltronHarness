"""Executa o benchmark comparativo Horizon Control v1 com avaliador privado externo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.research.horizon_control import MODES, HorizonControlRunner

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="ollama_research")
    parser.add_argument("--seed", type=int, default=53)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--contract-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = load_settings(ROOT)
    runner = HorizonControlRunner(
        settings,
        private_root=args.contract_root,
        model_name=args.model,
        seed=args.seed,
    )
    result = runner.run(limit=args.limit, modes=tuple(args.modes))
    payload = {
        "run_id": result.run_id,
        "artifact_dir": str(result.artifact_dir),
        "total": result.total,
        "measurement_valid": result.measurement_valid,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
