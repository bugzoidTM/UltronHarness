from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ultron.cognition.prediction import PredictionError, PredictionService
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    NextAction,
    OrientationSnapshot,
    Prediction,
    PredictionClassification,
    TaskCreate,
    VerificationSpec,
)
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _orchestrator(tmp_path: Path, *, enabled: bool = True) -> Orchestrator:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["memory"]["vector_enabled"] = False
    raw["cognition"]["controller_mode"] = "next_action"
    raw["cognition"].setdefault("feature_flags", {})["prediction_before_observation"] = enabled
    settings = Settings(raw=raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    return Orchestrator(
        settings,
        db,
        EventBus(db),
        MemoryService(db, settings),
        ModelGateway(settings),
        PolicyEngine(settings),
        ToolRegistry(settings),
    )


def _action() -> NextAction:
    return NextAction(
        intent="verificar a precondição",
        tool="python.execute",
        arguments={"code": "print('ok')"},
        expected_evidence=VerificationSpec(type="tool_success"),
        confidence=0.6,
    )


def _insert_action(orchestrator: Orchestrator, task: dict[str, Any], action_id: str, *, status: str = "proposed", executed_at: str | None = None) -> None:
    orchestrator.db.execute(
        """INSERT INTO cognitive_actions
           (id,action_id,task_id,iteration,tool,arguments_json,expected_evidence_json,status,created_at,executed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            action_id,
            action_id,
            task["id"],
            1,
            "python.execute",
            "{}",
            '{"type":"tool_success"}',
            status,
            "2026-08-25T00:00:00+00:00",
            executed_at,
        ),
    )


def test_prediction_round_trip_and_all_classifications(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    service = PredictionService(orchestrator.db)
    # Use a minimal persisted task row because this test exercises only the append-only service.
    orchestrator.db.execute(
        """INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("task-predictions", "Predictions", "Testar previsão", "created", 3, "predictions", 4, "2026-08-25T00:00:00+00:00", "2026-08-25T00:00:00+00:00"),
    )
    action = _action()
    outcomes = [
        ("confirm", "completed", True),
        ("weaken", "completed", False),
        ("reject", "failed", False),
        ("uncertain", "unknown", False),
    ]
    for index, (expected_classification, result_status, verification_passed) in enumerate(outcomes, start=1):
        action_id = f"action-{index}"
        _insert_action(orchestrator, {"id": "task-predictions"}, action_id)
        prediction = service.create(task_id="task-predictions", action_id=action_id, iteration=index, action=action)
        outcome = service.observe(
            prediction_id=prediction.prediction_id,
            action_id=action_id,
            observed_output=f"observação {index}",
            result_status=result_status,
            verification_passed=verification_passed,
            evidence_refs=[f"execution:{index}"],
        )
        assert outcome.classification.value == expected_classification
        materialized = service.materialize(prediction.prediction_id)
        assert materialized.observed == f"observação {index}"
        assert materialized.classification is PredictionClassification(expected_classification)
        assert materialized.evidence_refs == [f"execution:{index}"]


def test_prediction_schema_rejects_partial_observation() -> None:
    with pytest.raises(ValidationError, match="todos os campos"):
        Prediction(
            prediction_id="p",
            task_id="t",
            action_id="a",
            iteration=1,
            hypothesis="verificar",
            expected_observation="tool_success",
            confidence_before=0.5,
            action="verificar",
            predicted_at="2026-08-25T00:00:00+00:00",
            observed="resultado",
        )


def test_prediction_rejects_retrospective_and_duplicate_observation(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    service = PredictionService(orchestrator.db)
    orchestrator.db.execute(
        """INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("task-adversarial", "Predictions", "Testar ordem", "created", 3, "predictions", 4, "2026-08-25T00:00:00+00:00", "2026-08-25T00:00:00+00:00"),
    )
    _insert_action(orchestrator, {"id": "task-adversarial"}, "action-done", status="completed", executed_at="2026-08-25T00:00:01+00:00")
    with pytest.raises(PredictionError, match="precede"):
        service.create(task_id="task-adversarial", action_id="action-done", iteration=1, action=_action())

    _insert_action(orchestrator, {"id": "task-adversarial"}, "action-open")
    prediction = service.create(task_id="task-adversarial", action_id="action-open", iteration=1, action=_action())
    service.observe(
        prediction_id=prediction.prediction_id,
        action_id="action-open",
        observed_output="resultado",
        result_status="completed",
        verification_passed=True,
    )
    with pytest.raises(PredictionError, match="already_observed"):
        service.observe(
            prediction_id=prediction.prediction_id,
            action_id="action-open",
            observed_output="segunda observação",
            result_status="completed",
            verification_passed=True,
        )


@pytest.mark.asyncio
async def test_runtime_emits_prediction_before_action_and_observation(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=True)
    task = await orchestrator.create_task(
        TaskCreate(
            title="Prediction runtime",
            objective="Verificar uma precondição antes de concluir.",
            workspace="prediction_runtime",
            autonomy_mode=4,
            allowed_tools=["python.execute"],
            action_budget=(1, 2),
        )
    )
    snapshot = await orchestrator.horizon.ensure_initial_observation(
        task,
        orientation=OrientationSnapshot(mission_id=task["id"], observations=["workspace observado"]),
    )

    async def execute(_task_id: str, _call) -> dict[str, Any]:
        orchestrator.db.execute("UPDATE tasks SET tool_call_count=tool_call_count+1 WHERE id=?", (task["id"],))
        return {"status": "completed", "output": "precondição confirmada", "execution_id": "exec:prediction"}

    orchestrator.horizon.execute_tool = execute
    observation, updated, validation = await orchestrator.horizon.execute_iteration(task, _action(), snapshot)
    assert validation.accepted is True
    assert observation is not None and observation.verification_passed is True
    assert updated.iteration == 1
    prediction_rows = orchestrator.db.all("SELECT prediction_id FROM cognitive_predictions WHERE task_id=?", (task["id"],))
    assert len(prediction_rows) == 1
    events = orchestrator.db.all(
        "SELECT event_type,payload_json FROM execution_traces WHERE task_id=? AND event_type LIKE 'cognition.prediction.%' ORDER BY rowid",
        (task["id"],),
    )
    assert [row["event_type"] for row in events] == ["cognition.prediction.proposed", "cognition.prediction.observed"]
    proposed = orchestrator.db.parse_json(events[0]["payload_json"], {})
    observed = orchestrator.db.parse_json(events[1]["payload_json"], {})
    assert proposed["predicted_at"]
    assert observed["observed_at"]
    assert observed["classification"] == "confirm"
    assert proposed["prediction_id"] == observed["prediction_id"]


@pytest.mark.asyncio
async def test_prediction_flag_off_does_not_change_runtime(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=False)
    task = await orchestrator.create_task(
        TaskCreate(title="Prediction disabled", objective="Executar sem previsão nova.", workspace="prediction_off", autonomy_mode=4, allowed_tools=["python.execute"], action_budget=(1, 1))
    )
    snapshot = await orchestrator.horizon.ensure_initial_observation(task, orientation=OrientationSnapshot(mission_id=task["id"]))

    async def execute(_task_id: str, _call) -> dict[str, Any]:
        orchestrator.db.execute("UPDATE tasks SET tool_call_count=tool_call_count+1 WHERE id=?", (task["id"],))
        return {"status": "completed", "output": "ok", "execution_id": "exec:off"}

    orchestrator.horizon.execute_tool = execute
    await orchestrator.horizon.execute_iteration(task, _action(), snapshot)
    assert orchestrator.db.all("SELECT 1 FROM cognitive_predictions WHERE task_id=?", (task["id"],)) == []
    assert orchestrator.db.all("SELECT 1 FROM execution_traces WHERE task_id=? AND event_type LIKE 'cognition.prediction.%'", (task["id"],)) == []
