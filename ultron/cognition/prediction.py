"""Prediction Before Observation: previsões temporais, auditáveis e sem autoridade de execução."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.db import Database
from ultron.schemas import (
    NextAction,
    PlanStep,
    Prediction,
    PredictionClassification,
    VerificationSpec,
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class PredictionError(ValueError):
    """Erro de ordem, identidade ou duplicação no ciclo expected/observed."""


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    prediction_id: str
    classification: PredictionClassification
    confidence_after: float
    observed_output: str
    evidence_refs: list[str]
    observed_at: str


class PredictionService:
    """Persiste previsões e observações em tabelas append-only separadas."""

    def __init__(self, db: Database):
        self.db = db
        self.db.initialize()

    @staticmethod
    def expected_observation(action: NextAction | PlanStep) -> str:
        if isinstance(action, NextAction):
            spec: VerificationSpec = action.expected_evidence
            suffix = f":{spec.path}" if spec.path else ""
            return f"{spec.type}{suffix}"
        return action.success_condition

    @staticmethod
    def hypothesis(action: NextAction | PlanStep) -> str:
        return action.intent if isinstance(action, NextAction) else action.action

    @staticmethod
    def confidence_before(action: NextAction | PlanStep) -> float:
        return float(action.confidence) if isinstance(action, NextAction) else 0.5

    def create(
        self,
        *,
        task_id: str,
        action_id: str,
        iteration: int,
        action: NextAction | PlanStep,
    ) -> Prediction:
        action_row = self.db.one(
            "SELECT action_id,status,executed_at FROM cognitive_actions WHERE action_id=?",
            (str(action_id),),
        )
        if not action_row:
            raise PredictionError("prediction_action_not_found")
        if action_row.get("executed_at") is not None or action_row.get("status") in {"completed", "failed", "blocked"}:
            raise PredictionError("prediction_must_precede_observation")
        if self.db.one("SELECT prediction_id FROM cognitive_predictions WHERE action_id=?", (str(action_id),)):
            raise PredictionError("prediction_already_exists")
        prediction_id = str(uuid4())
        predicted_at = utcnow()
        prediction = Prediction(
            prediction_id=prediction_id,
            task_id=str(task_id),
            action_id=str(action_id),
            iteration=int(iteration),
            hypothesis=self.hypothesis(action),
            expected_observation=self.expected_observation(action),
            confidence_before=self.confidence_before(action),
            action=self.hypothesis(action),
            predicted_at=predicted_at,
        )
        self.db.execute(
            """INSERT INTO cognitive_predictions
               (id,prediction_id,task_id,action_id,iteration,hypothesis,expected_observation,confidence_before,action_json,predicted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                prediction.prediction_id,
                prediction.task_id,
                prediction.action_id,
                prediction.iteration,
                prediction.hypothesis,
                prediction.expected_observation,
                prediction.confidence_before,
                self.db.json(action.model_dump(mode="json")),
                predicted_at,
            ),
        )
        return prediction

    def observe(
        self,
        *,
        prediction_id: str,
        action_id: str,
        observed_output: str,
        result_status: str,
        verification_passed: bool,
        evidence_refs: list[str] | None = None,
    ) -> PredictionOutcome:
        prediction = self.db.one(
            "SELECT * FROM cognitive_predictions WHERE prediction_id=?",
            (str(prediction_id),),
        )
        if not prediction:
            raise PredictionError("prediction_not_found")
        if str(prediction["action_id"]) != str(action_id):
            raise PredictionError("prediction_action_mismatch")
        if self.db.one(
            "SELECT id FROM prediction_observations WHERE prediction_id=?",
            (str(prediction_id),),
        ):
            raise PredictionError("prediction_already_observed")
        if result_status == "waiting_approval":
            raise PredictionError("approval_is_not_an_observation")

        classification, confidence_after = self._classify(
            result_status=result_status,
            verification_passed=verification_passed,
            confidence_before=float(prediction["confidence_before"]),
        )
        observed_at = utcnow()
        refs = [str(item) for item in (evidence_refs or [])]
        self.db.execute(
            """INSERT INTO prediction_observations
               (id,prediction_id,task_id,action_id,observed_output,result_status,verification_passed,confidence_after,classification,evidence_refs_json,observed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                str(prediction_id),
                str(prediction["task_id"]),
                str(action_id),
                str(observed_output)[:2000],
                str(result_status),
                int(verification_passed),
                confidence_after,
                classification.value,
                self.db.json(refs),
                observed_at,
            ),
        )
        return PredictionOutcome(
            prediction_id=str(prediction_id),
            classification=classification,
            confidence_after=confidence_after,
            observed_output=str(observed_output)[:2000],
            evidence_refs=refs,
            observed_at=observed_at,
        )

    @staticmethod
    def _classify(
        *,
        result_status: str,
        verification_passed: bool,
        confidence_before: float,
    ) -> tuple[PredictionClassification, float]:
        if result_status == "completed" and verification_passed:
            return PredictionClassification.CONFIRM, max(confidence_before, 0.85)
        if result_status == "failed":
            return PredictionClassification.REJECT, min(confidence_before, 0.15)
        if result_status == "completed":
            return PredictionClassification.WEAKEN, min(confidence_before, 0.4)
        return PredictionClassification.UNCERTAIN, confidence_before

    def pending(self, *, task_id: str) -> list[Prediction]:
        rows = self.db.all(
            """SELECT p.* FROM cognitive_predictions p
               LEFT JOIN prediction_observations o ON o.prediction_id=p.prediction_id
               WHERE p.task_id=? AND o.id IS NULL ORDER BY p.predicted_at""",
            (str(task_id),),
        )
        return [self._prediction_from_row(row) for row in rows]

    def recent_summary(self, *, task_id: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT p.prediction_id,p.action_id,p.hypothesis,p.expected_observation,p.confidence_before,
                      o.observed_output,o.confidence_after,o.classification,o.evidence_refs_json,o.observed_at
               FROM cognitive_predictions p
               LEFT JOIN prediction_observations o ON o.prediction_id=p.prediction_id
               WHERE p.task_id=? ORDER BY p.predicted_at DESC LIMIT ?""",
            (str(task_id), int(limit)),
        )
        return [
            {
                "prediction_id": row["prediction_id"],
                "action_id": row["action_id"],
                "hypothesis": row["hypothesis"],
                "expected_observation": row["expected_observation"],
                "confidence_before": row["confidence_before"],
                "observed_output": row["observed_output"],
                "confidence_after": row["confidence_after"],
                "classification": row["classification"],
                "evidence_refs": self.db.parse_json(row["evidence_refs_json"], []),
                "observed_at": row["observed_at"],
            }
            for row in reversed(rows)
        ]

    @staticmethod
    def _prediction_from_row(row: dict[str, Any]) -> Prediction:
        action_payload = Database.parse_json(row["action_json"], {})
        return Prediction(
            prediction_id=str(row["prediction_id"]),
            task_id=str(row["task_id"]),
            action_id=str(row["action_id"]),
            iteration=int(row["iteration"]),
            hypothesis=str(row["hypothesis"]),
            expected_observation=str(row["expected_observation"]),
            confidence_before=float(row["confidence_before"]),
            action=str(action_payload.get("intent") or action_payload.get("action") or row["hypothesis"]),
            predicted_at=str(row["predicted_at"]),
        )

    def materialize(self, prediction_id: str) -> Prediction:
        row = self.db.one(
            """SELECT p.*,o.observed_output,o.confidence_after,o.classification,o.evidence_refs_json,o.observed_at
               FROM cognitive_predictions p LEFT JOIN prediction_observations o ON o.prediction_id=p.prediction_id
               WHERE p.prediction_id=?""",
            (str(prediction_id),),
        )
        if not row:
            raise PredictionError("prediction_not_found")
        action_payload = self.db.parse_json(row["action_json"], {})
        classification = row.get("classification")
        return Prediction(
            prediction_id=str(row["prediction_id"]),
            task_id=str(row["task_id"]),
            action_id=str(row["action_id"]),
            iteration=int(row["iteration"]),
            hypothesis=str(row["hypothesis"]),
            expected_observation=str(row["expected_observation"]),
            confidence_before=float(row["confidence_before"]),
            action=str(action_payload.get("intent") or action_payload.get("action") or row["hypothesis"]),
            observed=row.get("observed_output"),
            confidence_after=float(row["confidence_after"]) if row.get("confidence_after") is not None else None,
            classification=PredictionClassification(classification) if classification else None,
            evidence_refs=self.db.parse_json(row.get("evidence_refs_json"), []),
            predicted_at=str(row["predicted_at"]),
            observed_at=row.get("observed_at"),
        )
