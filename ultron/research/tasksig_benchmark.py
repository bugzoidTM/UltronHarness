"""Métricas determinísticas do benchmark TASKSIG-200."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ultron.cognition.task_signature import TaskSignatureClassifier


@dataclass(frozen=True, slots=True)
class TaskSignatureBenchmarkResult:
    total: int
    known_accuracy: float
    unknown_precision: float
    unknown_recall: float
    false_confident_rate: float

    @property
    def passed(self) -> bool:
        return self.unknown_recall >= 0.95 and self.false_confident_rate < 0.02


def evaluate(path: Path) -> TaskSignatureBenchmarkResult:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    known_total = known_correct = 0
    unknown_total = unknown_detected = predicted_unknown = false_confident = 0
    for task in tasks:
        expected = str(task["expected_family"])
        signature = TaskSignatureClassifier.classify(task)
        predicted = signature.family
        if expected == "unknown":
            unknown_total += 1
            unknown_detected += int(predicted == "unknown")
            false_confident += int(predicted != "unknown" and signature.uncertainty < 0.25)
        else:
            known_total += 1
            known_correct += int(predicted == expected)
        predicted_unknown += int(predicted == "unknown")
    return TaskSignatureBenchmarkResult(
        total=len(tasks),
        known_accuracy=round(known_correct / known_total, 6) if known_total else 0.0,
        unknown_precision=round(unknown_detected / predicted_unknown, 6) if predicted_unknown else 0.0,
        unknown_recall=round(unknown_detected / unknown_total, 6) if unknown_total else 0.0,
        false_confident_rate=round(false_confident / unknown_total, 6) if unknown_total else 0.0,
    )
