"""World Model empírico do Athena: prevê em shadow e nunca bloqueia ações."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ultron.db import Database


@dataclass(frozen=True, slots=True)
class WorldPrediction:
    id: str
    action: str
    predicted_success: float
    predicted_outcome: str
    context: dict[str, str]
    shadow: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.predicted_success <= 1.0:
            raise ValueError("Probabilidade prevista deve estar entre 0 e 1")


@dataclass(frozen=True, slots=True)
class WorldMetrics:
    observations: int
    prediction_accuracy: float
    brier_score: float


class WorldModel:
    """Modelo de frequência com smoothing, destinado exclusivamente à observação."""

    def __init__(self, db: Database | None = None):
        self.db = db
        self._observations: list[tuple[WorldPrediction, bool, str]] = []
        if self.db:
            self.db.initialize()

    def predict(self, action: str, context: dict[str, str] | None = None) -> WorldPrediction:
        """Prevê por frequência histórica da mesma ação; nunca altera um plano."""
        history = [actual for prediction, actual, _ in self._observations if prediction.action == action]
        successes = sum(history)
        probability = (successes + 1) / (len(history) + 2)
        return WorldPrediction(
            id=str(uuid4()),
            action=action,
            predicted_success=round(probability, 6),
            predicted_outcome="success" if probability >= 0.5 else "failure",
            context=dict(context or {}),
        )

    def observe(self, prediction: WorldPrediction, actual_success: bool, actual_outcome: str) -> None:
        """Registra o resultado posterior; observações não retroagem para decisões passadas."""
        self._observations.append((prediction, actual_success, actual_outcome))
        if self.db:
            self.db.execute(
                "INSERT INTO world_model_observations (id,action,predicted_success,predicted_outcome,actual_success,actual_outcome,context_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    prediction.id,
                    prediction.action,
                    prediction.predicted_success,
                    prediction.predicted_outcome,
                    int(actual_success),
                    actual_outcome,
                    json.dumps(prediction.context, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def metrics(self) -> WorldMetrics:
        if not self._observations:
            return WorldMetrics(0, 0.0, 0.0)
        correct = sum(
            (prediction.predicted_success >= 0.5) == actual
            for prediction, actual, _ in self._observations
        )
        brier = sum(
            (prediction.predicted_success - float(actual)) ** 2
            for prediction, actual, _ in self._observations
        ) / len(self._observations)
        return WorldMetrics(
            observations=len(self._observations),
            prediction_accuracy=round(correct / len(self._observations), 6),
            brier_score=round(brier, 6),
        )

    def shadow_record(self, action: str, context: dict[str, str] | None = None) -> dict:
        """Produz registro serializável sem executar ou impedir a ação proposta."""
        return asdict(self.predict(action, context))
