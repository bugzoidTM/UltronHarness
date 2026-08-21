"""Estatísticas leves e auditáveis para os experimentos do UltronPro."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import mean, median, stdev


@dataclass(frozen=True, slots=True)
class SummaryStatistics:
    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    stddev: float
    ci95_low: float
    ci95_high: float

    def model_dump(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "min": self.minimum,
            "max": self.maximum,
            "stddev": self.stddev,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


def summarize(values: Iterable[float]) -> SummaryStatistics:
    """Resume todos os valores, sem descartar seeds, runs ruins ou scores zero."""
    items = [float(value) for value in values]
    if not items:
        return SummaryStatistics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    average = mean(items)
    deviation = stdev(items) if len(items) > 1 else 0.0
    margin = 1.96 * deviation / math.sqrt(len(items)) if len(items) > 1 else 0.0
    return SummaryStatistics(
        count=len(items),
        mean=round(average, 6),
        median=round(median(items), 6),
        minimum=round(min(items), 6),
        maximum=round(max(items), 6),
        stddev=round(deviation, 6),
        ci95_low=round(average - margin, 6),
        ci95_high=round(average + margin, 6),
    )


def effect_delta(experienced: Iterable[float], fresh: Iterable[float]) -> SummaryStatistics:
    """Calcula o delta pareado por índice e falha se as condições não forem comparáveis."""
    left, right = [float(value) for value in experienced], [float(value) for value in fresh]
    if len(left) != len(right):
        raise ValueError("Condições não comparáveis: quantidades de resultados diferentes.")
    return summarize([item - baseline for item, baseline in zip(left, right, strict=True)])
