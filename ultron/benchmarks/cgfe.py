"""Experimento Capability Gain From Experience (CGFE) local, auditável e sem autoalteração."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import Settings


@dataclass(slots=True)
class CGFEResult:
    experiment_id: str
    fresh_score: float
    experienced_score: float
    cgfe: float
    recovery_gain: float
    efficiency_gain: float
    fresh_run_id: str
    experienced_run_id: str
    report_dir: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "fresh_score": self.fresh_score,
            "experienced_score": self.experienced_score,
            "cgfe": self.cgfe,
            "recovery_gain": self.recovery_gain,
            "efficiency_gain": self.efficiency_gain,
            "fresh_run_id": self.fresh_run_id,
            "experienced_run_id": self.experienced_run_id,
            "report_dir": str(self.report_dir),
        }


class CGFEExperiment:
    """Compara a mesma configuração em condição sem e com experiência prévia não derivada do benchmark."""

    def __init__(self, settings: Settings, model_name: str | None = None, seed: int = 42):
        self.settings, self.model_name, self.seed = settings, model_name, seed

    def _experience_corpus(self, count: int) -> list[str]:
        # Corpus procedural, escrito manualmente, sem IDs, objetivos, fixtures ou respostas UGIB-Lite.
        base = [
            "[reasoning] Resolva a relação pedida passo a passo internamente e devolva somente o formato final solicitado.",
            "[coding] Responda estritamente com a construção ou identificador solicitado, sem explicações adicionais.",
            "[tool_use] Escolha apenas a ferramenta permitida cuja finalidade corresponde à operação descrita.",
            "[recovery] Identifique a categoria observável da falha antes de propor qualquer nova tentativa.",
            "[tool_use] Preserve a restrição de workspace e prefira evidência verificável sobre suposições.",
            "[recovery] Não repita uma ação bloqueada sem uma mudança segura e verificável de pré-condição.",
        ]
        return [base[index % len(base)] for index in range(count)]

    async def run_async(self, experience_count: int = 50) -> CGFEResult:
        fresh = UGIBLiteRunner(self.settings)
        fresh_manifest, fresh_summary = await fresh.run_async("ultron-fresh", self.model_name, self.seed)
        fresh_dir = self.settings.artifacts_dir / "benchmarks" / fresh_manifest.run_id
        fresh_dir.mkdir(parents=True, exist_ok=True)
        fresh.persist_run(fresh_manifest, fresh_summary, fresh_dir)

        corpus = self._experience_corpus(experience_count)
        # A barreira abaixo impede inclusão acidental de conteúdo de tarefa ou respostas privadas.
        task_text = "\n".join(task.objective for task in fresh.load_tasks()).casefold()
        if any(item.casefold() in task_text for item in corpus):
            raise RuntimeError("Data leakage detectado: experiência coincide com texto do benchmark.")

        experienced = UGIBLiteRunner(self.settings)
        experienced_manifest, experienced_summary = await experienced.run_async(
            "ultron-experienced", self.model_name, self.seed, experience_context=corpus
        )
        exp_dir = self.settings.artifacts_dir / "benchmarks" / experienced_manifest.run_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        experienced.persist_run(experienced_manifest, experienced_summary, exp_dir)

        experiment_id = str(uuid4())
        report_dir = self.settings.artifacts_dir / "experiments" / experiment_id
        report_dir.mkdir(parents=True, exist_ok=True)
        result = CGFEResult(
            experiment_id, fresh_summary.score, experienced_summary.score,
            round(experienced_summary.score - fresh_summary.score, 4),
            round(experienced_summary.recovery_rate - fresh_summary.recovery_rate, 4),
            round(fresh_summary.average_latency_ms - experienced_summary.average_latency_ms, 4),
            fresh_manifest.run_id, experienced_manifest.run_id, report_dir,
        )
        payload = {"result": result.as_dict(), "seed": self.seed, "model": self.model_name or self.settings.raw["models"]["primary"], "experience_count": experience_count, "leakage_protection": "experiências procedurais não contêm objetivos, IDs, fixtures ou contratos privados do UGIB-Lite", "created_at": datetime.now(UTC).isoformat()}
        (report_dir / "cgfe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_dir / "cgfe.md").write_text(
            f"# Relatório CGFE\n\n| Métrica | Valor |\n|---|---:|\n| Fresh | {result.fresh_score:.4f} |\n| Experienced | {result.experienced_score:.4f} |\n| CGFE | {result.cgfe:+.4f} |\n| Recovery gain | {result.recovery_gain:+.4f} |\n| Efficiency gain (ms) | {result.efficiency_gain:+.4f} |\n\nO resultado é uma medição observada; não implica causalidade além da configuração registrada.\n",
            encoding="utf-8",
        )
        return result

    def run(self, experience_count: int = 50) -> CGFEResult:
        return asyncio.run(self.run_async(experience_count))
