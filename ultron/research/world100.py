"""WORLD-100: calibração do World Model apenas com resultados reais de benchmarks persistidos."""

from __future__ import annotations

import json
from pathlib import Path

from ultron.cognition.world_model import WorldModel
from ultron.research.hermes_shadow import (
    OutcomeObservation,
    WorldCalibrationMetrics,
    calibrate_world_model,
)


def observations_from_transfer_artifacts(root: Path) -> list[OutcomeObservation]:
    observations: list[OutcomeObservation] = []
    for artifact in sorted(root.glob("*/transfer.json")):
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        for mode in ("fresh", "experienced"):
            for trace in payload.get("traces", {}).get(mode, []):
                observations.append(
                    OutcomeObservation(str(trace["family"]), 0.0, bool(trace["success"]))
                )
    return observations


def run_world100_from_transfer(root: Path) -> WorldCalibrationMetrics:
    raw = observations_from_transfer_artifacts(root)
    if len(raw) < 100:
        raise ValueError("WORLD-100 requer no mínimo 100 outcomes reais de Transfer-100")
    model = WorldModel()
    calibrated: list[OutcomeObservation] = []
    for observation in raw[:100]:
        prediction = model.predict(observation.action_family)
        model.observe(prediction, observation.actual_success, "success" if observation.actual_success else "failure")
        calibrated.append(OutcomeObservation(observation.action_family, prediction.predicted_success, observation.actual_success))
    return calibrate_world_model(calibrated)
