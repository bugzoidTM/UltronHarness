"""Consolida checkpoints Transfer-100 v3 sem misturar per-task e batched."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultron.research.statistics import summarize

CONDITIONS = ("never_inject", "always_inject", "router_use_abstain_reject")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed42", type=Path, required=True)
    parser.add_argument("--remaining", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    first = json.loads(args.seed42.read_text(encoding="utf-8"))
    remaining = json.loads(args.remaining.read_text(encoding="utf-8"))
    results = sorted([*first["results"], *remaining["results"]], key=lambda item: int(item["seed"]))
    seeds = [int(item["seed"]) for item in results]
    if seeds != [42, 43, 44]:
        raise SystemExit(f"Consolidado requer checkpoints 42, 43 e 44; encontrado {seeds}")
    condition_series = {condition: [float(item["conditions"][condition]) for item in results] for condition in CONDITIONS}
    report = {
        "benchmark": "transfer100_v3",
        "benchmark_version": "transfer100-v3-routing-per-task",
        "execution_mode": "per_task",
        "model": first["model"],
        "requested_seeds": [42, 43, 44],
        "completed_seeds": seeds,
        "status": "completed",
        "conditions": list(CONDITIONS),
        "results": results,
        "statistics": {condition: summarize(values).model_dump() for condition, values in condition_series.items()},
        "statistics_transfer_gain_router": summarize([float(item["transfer_gain_vs_never"]["router_use_abstain_reject"]) for item in results]).model_dump(),
        "statistics_abstention_value": summarize([float(item["abstention_value"]) for item in results]).model_dump(),
        "statistics_harmful_retrieval_rate_always": summarize([float(item["harmful_retrieval_rate"]["always_inject"]) for item in results]).model_dump(),
        "batched_control": first.get("batched_control", []),
        "batched_control_scope": "Somente seed 42; diagnóstico de formato separado e não agregado às métricas per-task.",
        "gate": {
            "decision": "SHADOW_RETAINED_NO_PROMOTION",
            "rationale": "O Router permaneceu em ABSTAIN na ausência de evidência pareada suficiente. Nenhuma família é promovida ao contexto ativo com base neste experimento.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
