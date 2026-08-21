"""CLI: python -m ultron.benchmarks run ugib-lite --mode baseline --seed 42."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ultron.benchmarks.ablations import AblationStudy
from ultron.benchmarks.cgfe import CGFEExperiment
from ultron.benchmarks.model_research import ModelResearch
from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import load_settings
from ultron.research.diagnostics import DiagnosticHarness


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m ultron.benchmarks")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Executa um benchmark local reproduzível.")
    run.add_argument("benchmark", choices=["ugib-lite"])
    run.add_argument("--model", default=None, help="Nome do modelo registrado em config/default.yaml")
    run.add_argument(
        "--mode",
        choices=["baseline", "tools", "ultron-fresh", "ultron-experienced"],
        default="baseline",
    )
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--task", default=None)
    run.add_argument("--category", choices=["reasoning", "coding", "tool_use", "recovery"], default=None)
    run.add_argument("--report", default=None, help="Diretório de saída opcional para o relatório.")
    compare = commands.add_parser("compare-models", help="Compara modelos locais no UGIB-Lite.")
    compare.add_argument("--models", nargs="+", default=None, help="Modelos registrados a comparar.")
    compare.add_argument("--mode", choices=["baseline", "tools", "ultron-fresh", "ultron-experienced"], default="baseline")
    compare.add_argument("--seed", type=int, default=42)
    compare.add_argument("--category", choices=["reasoning", "coding", "tool_use", "recovery"], default=None)
    cgfe = commands.add_parser("cgfe", help="Executa fresh → experiência → experienced e relata capability gain.")
    cgfe.add_argument("--model", default=None)
    cgfe.add_argument("--seed", type=int, default=42)
    cgfe.add_argument("--experiences", type=int, default=50)
    ablate = commands.add_parser("ablate", help="Executa as variantes A–F com política explícita de regressão.")
    ablate.add_argument("--model", default=None)
    ablate.add_argument("--seed", type=int, default=42)
    for command, help_text in [("memory-topk", "Executa o diagnóstico MEM-1 de sensibilidade Top-K."), ("memory-types", "Executa a ablação MEM-2 de tipos de memória."), ("retrieval-quality", "Executa o diagnóstico MEM-3 de qualidade de retrieval."), ("context-ablation", "Executa CTX-1/CTX-2 para contabilidade e ablação de contexto."), ("model-matrix", "Executa MODEL-1 para a matriz de capacidade."), ("orchestrator-cost", "Executa ORCH-1 para custo da orquestração."), ("multi-seed", "Executa o diagnóstico SEED-1 preservando todas as seeds."), ("experience-scaling", "Executa o diagnóstico LEARN-1 de escala de experiências."), ("learn2", "Executa LEARN-2 com experiências verificadas e filtradas.")]:
        diagnostic = commands.add_parser(command, help=help_text)
        diagnostic.add_argument("--model", default=None)
        diagnostic.add_argument("--seed", type=int, default=42)
        diagnostic.add_argument("--seeds", nargs="*", type=int, default=None)
        diagnostic.add_argument("--experiences", type=int, default=50)
    return root


def _write_report(root: Path, manifest: object, summary: object) -> Path:
    report_dir = root / "data" / "artifacts" / "benchmarks" / manifest.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (report_dir / "results.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (report_dir / "events.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "task_id": item.task.id,
                    "score": item.evaluation.score,
                    "success": item.evaluation.success,
                    "failure_category": item.execution.failure_category,
                    "duration_ms": item.execution.duration_ms,
                },
                ensure_ascii=False,
            )
            for item in summary.results
        )
        + "\n",
        encoding="utf-8",
    )
    metrics = summary.model_dump(exclude={"results"})
    (report_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# UGIB-Lite Run Summary",
        "",
        f"- Run: `{summary.run_id}`",
        f"- Mode: `{summary.mode}`",
        f"- Model: `{manifest.model}`",
        f"- Score: **{summary.score:.2%}** ({summary.passed}/{summary.total})",
        f"- Recovery rate: **{summary.recovery_rate:.2%}**",
        f"- Average latency: **{summary.average_latency_ms:.0f} ms**",
        "",
        "## Per-task results",
        "",
        "| Task | Category | Score | Status | Evidence |",
        "|---|---|---:|---|---|",
    ]
    for item in summary.results:
        lines.append(
            f"| {item.task.id} | {item.task.category} | {item.evaluation.score:.2f} | "
            f"{'PASS' if item.evaluation.success else 'FAIL'} | {'; '.join(item.evaluation.evidence) or '-'} |"
        )
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_dir


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    runner = UGIBLiteRunner(settings)
    manifest, summary = await runner.run_async(
        mode=args.mode,
        model_name=args.model,
        seed=args.seed,
        task_id=args.task,
        category=args.category,
    )
    report_dir = _write_report(settings.root_dir, manifest, summary)
    runner.persist_run(manifest, summary, report_dir)
    if args.report:
        custom = Path(args.report).resolve()
        custom.mkdir(parents=True, exist_ok=True)
        for item in report_dir.iterdir():
            (custom / item.name).write_bytes(item.read_bytes())
    print(f"UGIB-Lite run={summary.run_id} mode={summary.mode} score={summary.score:.2%} report={report_dir}")
    return 0


async def _cgfe(args: argparse.Namespace) -> int:
    result = await CGFEExperiment(load_settings(), args.model, args.seed).run_async(args.experiences)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


async def _ablate(args: argparse.Namespace) -> int:
    result = await AblationStudy(load_settings(), args.model, args.seed).run_async()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _diagnostic(args: argparse.Namespace) -> int:
    harness = DiagnosticHarness(load_settings(), args.model, args.seed)
    if args.command == "memory-topk":
        result = await harness.memory_topk()
    elif args.command == "memory-types":
        result = await harness.memory_types()
    elif args.command == "retrieval-quality":
        result = harness.retrieval_quality()
    elif args.command == "context-ablation":
        result = await harness.context_ablation()
    elif args.command == "model-matrix":
        result = await harness.model_matrix()
    elif args.command == "orchestrator-cost":
        result = await harness.orchestrator_cost()
    elif args.command == "multi-seed":
        result = await harness.multi_seed_cgfe(args.seeds, args.experiences)
    elif args.command == "learn2":
        result = await harness.learn2([0, 10, 25, 50, 100, 200])
    else:
        result = await harness.experience_scaling([10, 25, args.experiences, 100, 200])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _compare(args: argparse.Namespace) -> int:
    settings = load_settings()
    research = ModelResearch(settings)
    models = args.models or research.configured_research_models()
    results = await research.compare(models=models, mode=args.mode, seed=args.seed, category=args.category)
    print(json.dumps([item.model_dump() for item in results], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = parser().parse_args()
    if args.command == "run":
        return asyncio.run(_run(args))
    if args.command == "compare-models":
        return asyncio.run(_compare(args))
    if args.command == "cgfe":
        return asyncio.run(_cgfe(args))
    if args.command == "ablate":
        return asyncio.run(_ablate(args))
    if args.command in {"memory-topk", "memory-types", "retrieval-quality", "context-ablation", "model-matrix", "orchestrator-cost", "multi-seed", "experience-scaling", "learn2"}:
        return asyncio.run(_diagnostic(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
