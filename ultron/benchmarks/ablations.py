"""Ablações controladas do UltronPro; todas usam o mesmo modelo, seed e benchmark."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import Settings

VARIANTS = {
    "A": ("LLM only", "baseline", []),
    "B": ("LLM + tools", "tools", []),
    "C": ("LLM + tools + orchestrator", "ultron-fresh", []),
    "D": ("Ultron + memory disabled", "ultron-fresh", []),
    "E": ("Ultron + memory", "ultron-experienced", ["Use evidência procedimental relevante sem substituir o objetivo atual."]),
    "F": ("Ultron + memory + skills", "ultron-experienced", ["Use evidência procedimental relevante sem substituir o objetivo atual.", "Skill validada: identificar ferramenta permitida, executar em workspace isolado e verificar saída."]),
}


class AblationStudy:
    def __init__(self, settings: Settings, model_name: str | None = None, seed: int = 42):
        self.settings, self.model_name, self.seed = settings, model_name, seed

    async def run_async(self) -> dict[str, Any]:
        study_id = str(uuid4())
        records: list[dict[str, Any]] = []
        for code, (label, mode, context) in VARIANTS.items():
            runner = UGIBLiteRunner(self.settings)
            manifest, summary = await runner.run_async(mode, self.model_name, self.seed, experience_context=context)
            folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            folder.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, folder)
            records.append({"variant": code, "label": label, "mode": mode, "run_id": manifest.run_id, "score": summary.score, "recovery_rate": summary.recovery_rate, "latency_ms": summary.average_latency_ms})
        baseline = next(item for item in records if item["variant"] == "C")
        for item in records:
            item["delta_vs_c"] = round(item["score"] - baseline["score"], 4)
            item["regression"] = item["delta_vs_c"] < -0.02
        data = {"study_id": study_id, "seed": self.seed, "model": self.model_name or self.settings.raw["models"]["primary"], "created_at": datetime.now(UTC).isoformat(), "policy": "A variante só é considerada não-regressiva se delta_vs_c >= -0.02; resultados são evidência observacional.", "results": records}
        folder = self.settings.artifacts_dir / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (folder / f"ablation_{stamp}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# Ablações UltronPro", "", "| Var. | Configuração | Score | Δ vs C | Regressão |", "|---|---|---:|---:|---|"]
        lines.extend(f"| {r['variant']} | {r['label']} | {r['score']:.4f} | {r['delta_vs_c']:+.4f} | {'SIM' if r['regression'] else 'não'} |" for r in records)
        lines.append("\nA política marca regressão quando a diferença de score para C é inferior a -0,02.")
        (folder / f"ablation_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return data

    def run(self) -> dict[str, Any]:
        return asyncio.run(self.run_async())
