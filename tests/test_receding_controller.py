from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.receding_controller import RecedingHorizonController
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.models.gateway import ModelGateway
from ultron.schemas import CognitiveStateSnapshot, NextAction, VerificationSpec
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _controller(tmp_path: Path) -> tuple[RecedingHorizonController, dict]:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["memory"]["vector_enabled"] = False
    db = Database(settings.db_path)
    db.initialize()
    task = {
        "id": str(uuid4()),
        "objective": "Inspecionar artefatos autorizados.",
        "workspace": "horizon_controller",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": [1, 3],
        "tool_call_count": 0,
        "replan_count": 0,
    }
    db.execute(
        "INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,allowed_tools_json,action_budget_min,action_budget_max,created_at,updated_at) VALUES (?, ?, ?, 'created', 0.5, ?, 4, ?, 1, 3, 'now', 'now')",
        (task["id"], "Horizon", task["objective"], task["workspace"], db.json(task["allowed_tools"])),
    )

    async def execute_tool(_task_id: str, call) -> dict:
        return {
            "status": "completed",
            "execution_id": "exec-1",
            "output": f"executed:{call.tool_name}",
            "error": None,
        }

    tools = ToolRegistry(settings)
    controller = RecedingHorizonController(
        settings,
        db,
        EventBus(db),
        ModelGateway(settings),
        tools,
        StepSuccessVerifier(tools),
        execute_tool,
        planning_seed=53,
    )
    return controller, task


@pytest.mark.asyncio
async def test_next_action_cannot_escape_allowed_tools(tmp_path: Path) -> None:
    controller, task = _controller(tmp_path)
    snapshot = controller.latest_snapshot(task)
    action = NextAction(
        intent="Escrever fora do contrato",
        tool="file.write",
        arguments={"path": "x.txt", "content": "x"},
        expected_evidence=VerificationSpec(type="tool_success"),
    )

    observation, updated, validation = await controller.execute_iteration(task, action, snapshot)

    assert observation is None
    assert updated == snapshot
    assert not validation.accepted
    assert validation.reason == "tool_outside_mission_contract"


@pytest.mark.asyncio
async def test_successful_action_persists_observation_before_next_decision(tmp_path: Path) -> None:
    controller, task = _controller(tmp_path)
    snapshot = CognitiveStateSnapshot(
        task_id=task["id"],
        objective=task["objective"],
        remaining_action_budget=3,
    )
    action = NextAction(
        intent="Listar arquivos",
        tool="file.list",
        arguments={"path": "."},
        expected_evidence=VerificationSpec(type="tool_success"),
    )

    observation, updated, validation = await controller.execute_iteration(task, action, snapshot)

    assert validation.accepted
    assert observation is not None and observation.verification_passed
    assert updated.iteration == 1
    assert controller.db.one("SELECT iteration FROM cognitive_snapshots WHERE task_id=?", (task["id"],)) == {"iteration": 1}
    action_row = controller.db.one("SELECT status FROM cognitive_actions WHERE task_id=?", (task["id"],))
    assert action_row == {"status": "completed"}


@pytest.mark.asyncio
async def test_next_action_requires_observation_before_next_decision(tmp_path: Path) -> None:
    controller, task = _controller(tmp_path)
    controller.db.execute(
        "INSERT INTO cognitive_actions (id,action_id,task_id,iteration,arguments_json,expected_evidence_json,status,created_at) VALUES (?, ?, ?, 1, '{}', '{}', 'proposed', 'now')",
        (str(uuid4()), str(uuid4()), task["id"]),
    )
    snapshot = controller.latest_snapshot(task)

    with pytest.raises(RuntimeError, match="OBSERVATION_REQUIRED"):
        await controller.decide_next_action(task, snapshot)


def test_controller_cannot_expand_global_or_mission_budget(tmp_path: Path) -> None:
    controller, task = _controller(tmp_path)
    controller.settings.raw["limits"]["max_tool_calls"] = 2
    task["action_budget"] = [1, 9]
    assert controller.contract.remaining_budget(task) == 2
    task["tool_call_count"] = 2
    assert controller.contract.remaining_budget(task) == 0


def test_snapshot_roundtrip_from_persistence(tmp_path: Path) -> None:
    controller, task = _controller(tmp_path)
    original = CognitiveStateSnapshot(
        task_id=task["id"],
        objective=task["objective"],
        known_facts=["a"],
        recent_observations=["b"],
        remaining_action_budget=2,
        iteration=1,
    )
    controller.persist_snapshot(original)
    assert controller.latest_snapshot(task) == original


if __name__ == "__main__":
    asyncio.run(asyncio.sleep(0))
