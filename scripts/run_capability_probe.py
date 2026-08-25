"""Executa um probe público curto para orientar iterações de capacidade do Ultron.

Este runner é deliberadamente development-only: não acessa o benchmark privado GR,
não produz evidência confirmatória e não altera o protocolo congelado.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import load_settings

DEFAULT_TASKS = [
    "reasoning_01",
    "reasoning_04",
    "coding_01",
    "coding_04",
    "tool_use_01",
    "tool_use_04",
    "recovery_01",
    "recovery_04",
]
DEFAULT_VARIANTS = ("baseline", "ultron-fresh")
SCHEMA_VERSION = "capability_probe_v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe público curto e resumível; não é evidência científica confirmatória."
    )
    parser.add_argument("--model", default="ollama_research", help="Modelo registrado em config/default.yaml.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tasks", nargs="+", default=None, help="IDs públicos; por padrão, 2 por categoria.")
    parser.add_argument("--max-tasks", type=int, default=8)
    parser.add_argument("--max-new-variants", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None, help="Diretório de um probe parcial anterior.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _task_ids(runner: UGIBLiteRunner, requested: list[str] | None, max_tasks: int) -> list[str]:
    if max_tasks < 1:
        raise ValueError("--max-tasks deve ser maior que zero.")
    available = {task.id for task in runner.load_tasks()}
    selected = list(dict.fromkeys(requested or DEFAULT_TASKS))[:max_tasks]
    missing = [task_id for task_id in selected if task_id not in available]
    if missing:
        raise ValueError(f"Tarefas públicas ausentes: {', '.join(missing)}")
    return selected


def _probe_dir(args: argparse.Namespace, root: Path) -> Path:
    if args.resume:
        return args.resume.resolve()
    if args.output:
        return args.output.resolve()
    return (root / "data" / "artifacts" / "research" / "capability_probe" / f"probe_{_utc_stamp()}").resolve()


def _checkpoint_path(probe_dir: Path) -> Path:
    return probe_dir / "checkpoint.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _new_checkpoint(args: argparse.Namespace, task_ids: list[str]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "scientific_use": "development_only",
        "model": args.model,
        "seed": args.seed,
        "task_ids": task_ids,
        "variants": list(DEFAULT_VARIANTS),
        "completed_variants": {},
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _load_or_create_checkpoint(args: argparse.Namespace, probe_dir: Path, task_ids: list[str]) -> dict[str, Any]:
    path = _checkpoint_path(probe_dir)
    if not path.exists():
        checkpoint = _new_checkpoint(args, task_ids)
        _write_json(path, checkpoint)
        return checkpoint
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("schema") != SCHEMA_VERSION:
        raise ValueError("Checkpoint de capability probe incompatível.")
    if checkpoint.get("model") != args.model or int(checkpoint.get("seed", args.seed)) != args.seed:
        raise ValueError("--model/--seed não correspondem ao checkpoint; use os valores congelados do probe.")
    if checkpoint.get("task_ids") != task_ids:
        raise ValueError("A lista de tarefas não corresponde ao checkpoint; não misture probes.")
    return checkpoint


def _variant_result(manifest: Any, summary: Any) -> dict[str, Any]:
    item = summary.results[0]
    return {
        "run_id": manifest.run_id,
        "task_id": item.task.id,
        "variant": str(item.task and summary.mode),
        "model": manifest.model,
        "seed": manifest.seed,
        "success": bool(item.evaluation.success),
        "score": float(item.evaluation.score),
        "failure_category": item.execution.failure_category,
        "duration_ms": int(item.execution.duration_ms),
        "tool_calls": len(item.execution.tool_calls),
        "artifact_paths": list(item.execution.artifact_paths),
        "scientific_use": "development_only",
    }


def _write_summary(probe_dir: Path, checkpoint: dict[str, Any], status: str) -> None:
    completed = list(checkpoint["completed_variants"].values())
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in completed:
        by_variant[result["variant"]].append(result)
    lines = [
        "# Capability Probe Público",
        "",
        "> Artefato **development-only**. Não é validation, não é unseen e não sustenta claim de AGI, lift ou generalização.",
        "",
        f"- Status: **{status}**",
        f"- Modelo: `{checkpoint['model']}`",
        f"- Seed: `{checkpoint['seed']}`",
        f"- Tarefas: **{len(checkpoint['task_ids'])}**",
        f"- Variantes planejadas: `{', '.join(checkpoint['variants'])}`",
        "",
        "## Resumo por variante",
        "",
        "| Variante | Execuções | Sucessos | Score médio | Latência média (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for variant in checkpoint["variants"]:
        rows = by_variant.get(variant, [])
        successes = sum(int(row["success"]) for row in rows)
        score = sum(row["score"] for row in rows) / len(rows) if rows else 0.0
        latency = sum(row["duration_ms"] for row in rows) / len(rows) if rows else 0.0
        lines.append(f"| {variant} | {len(rows)} | {successes} | {score:.3f} | {latency:.0f} |")
    lines.extend(
        [
            "",
            "## Escopo e interpretação",
            "",
            "Este probe usa somente tarefas públicas do UGIB-Lite e serve para ciclos rápidos de engenharia. Uma diferença entre variantes é um sinal para investigação, não uma estimativa confirmatória: faltam múltiplas seeds, split privado inédito, IC95 pré-registrado e auditoria de leakage do benchmark GR.",
            "",
            "## Resultados por execução",
            "",
            "| Tarefa | Variante | Sucesso | Score | Latência (ms) | Falha |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for row in sorted(completed, key=lambda value: (value["task_id"], value["variant"])):
        lines.append(
            f"| {row['task_id']} | {row['variant']} | {'PASS' if row['success'] else 'FAIL'} | "
            f"{row['score']:.3f} | {row['duration_ms']} | {row['failure_category'] or '-'} |"
        )
    (probe_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(
        probe_dir / "manifest.json",
        {
            "schema": SCHEMA_VERSION,
            "scientific_use": "development_only",
            "status": status,
            "model": checkpoint["model"],
            "seed": checkpoint["seed"],
            "task_ids": checkpoint["task_ids"],
            "variants": checkpoint["variants"],
            "completed_variants": len(completed),
            "planned_variants": len(checkpoint["task_ids"]) * len(checkpoint["variants"]),
            "created_at": checkpoint["created_at"],
            "updated_at": checkpoint["updated_at"],
        },
    )


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    runner = UGIBLiteRunner(settings)
    task_ids = _task_ids(runner, args.tasks, args.max_tasks)
    if args.max_new_variants is not None and args.max_new_variants < 1:
        raise ValueError("--max-new-variants deve ser maior que zero quando informado.")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "schema": SCHEMA_VERSION,
                    "scientific_use": "development_only",
                    "model": args.model,
                    "seed": args.seed,
                    "task_ids": task_ids,
                    "variants": list(DEFAULT_VARIANTS),
                    "planned_variants": len(task_ids) * len(DEFAULT_VARIANTS),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    probe_dir = _probe_dir(args, settings.root_dir)
    probe_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = _load_or_create_checkpoint(args, probe_dir, task_ids)
    completed: dict[str, dict[str, Any]] = checkpoint["completed_variants"]
    new_variants = 0
    for task_id in task_ids:
        for variant in DEFAULT_VARIANTS:
            key = f"{task_id}:{variant}"
            if key in completed:
                continue
            if args.max_new_variants is not None and new_variants >= args.max_new_variants:
                _write_summary(probe_dir, checkpoint, "partial")
                print(f"Probe parcial preservado em {probe_dir}")
                return 0
            print(f"[probe] {new_variants + 1}: {task_id} / {variant}", flush=True)
            manifest, summary = await runner.run_async(
                mode=variant,
                model_name=args.model,
                seed=args.seed,
                task_id=task_id,
            )
            report_dir = probe_dir / "runs" / key.replace(":", "__")
            report_dir.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, report_dir)
            result = _variant_result(manifest, summary)
            result["variant"] = variant
            completed[key] = result
            checkpoint["updated_at"] = datetime.now(UTC).isoformat()
            _write_json(_checkpoint_path(probe_dir), checkpoint)
            new_variants += 1
    _write_summary(probe_dir, checkpoint, "complete")
    print(f"Probe completo preservado em {probe_dir}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
