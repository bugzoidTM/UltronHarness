"""Benchmark comparativo de runtimes locais sem hardcode de modelo de pesquisa."""

from __future__ import annotations

from time import perf_counter

import psutil

from ultron.benchmarks.models import BenchmarkMode, ModelBenchmarkResult
from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import Settings


class ModelResearch:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runner = UGIBLiteRunner(settings)

    async def compare(
        self,
        models: list[str],
        mode: BenchmarkMode = "baseline",
        seed: int = 42,
        category: str | None = None,
    ) -> list[ModelBenchmarkResult]:
        results: list[ModelBenchmarkResult] = []
        process = psutil.Process()
        for model in models:
            started = perf_counter()
            memory_before = process.memory_info().rss
            manifest, summary = await self.runner.run_async(
                mode=mode, model_name=model, seed=seed, category=category
            )
            memory_after = process.memory_info().rss
            elapsed = max(perf_counter() - started, 0.001)
            invalid = sum(bool(item.execution.failure_category) for item in summary.results)
            tokens = sum(len(item.execution.response.split()) for item in summary.results)
            result = ModelBenchmarkResult(
                model=model,
                score=summary.score,
                task_success_rate=round(summary.passed / max(summary.total, 1), 4),
                invalid_output_rate=round(invalid / max(summary.total, 1), 4),
                average_latency_ms=summary.average_latency_ms,
                tokens_per_second=round(tokens / elapsed, 4) if tokens else None,
                ram_peak_mb=round(max(memory_before, memory_after) / 1024 / 1024, 2),
                vram_peak_mb=None,
            )
            report_dir = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            report_dir.mkdir(parents=True, exist_ok=True)
            self.runner.persist_run(manifest, summary, report_dir)
            results.append(result)
        return results

    def configured_research_models(self) -> list[str]:
        configured = self.settings.raw["models"]
        candidates = [configured.get("research_primary"), configured.get("research_secondary")]
        return [item for item in candidates if isinstance(item, str) and item]
