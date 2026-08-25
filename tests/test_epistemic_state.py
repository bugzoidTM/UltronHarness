from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ultron.cognition.epistemic import (
    initial_state,
    record_assumption,
    record_hypothesis,
    record_inference,
    record_unknown,
)
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    EpistemicClaim,
    EpistemicKind,
    EpistemicState,
    NextAction,
    OrientationSnapshot,
    Plan,
    PlanStep,
    TaskCreate,
    VerificationSpec,
)
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _orchestrator(tmp_path: Path, *, enabled: bool) -> Orchestrator:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["memory"]["vector_enabled"] = False
    raw["cognition"]["controller_mode"] = "next_action"
    raw["cognition"].setdefault("feature_flags", {})["epistemic_state"] = enabled
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


@pytest.mark.parametrize("builder", [record_inference, record_assumption, record_hypothesis, record_unknown])
def test_epistemic_kinds_remain_partitioned(builder) -> None:
    state = initial_state("Verificar precondição")
    if builder is record_hypothesis:
        updated = builder(state, "A precondição existe", confidence=0.4)
    else:
        updated = builder(state, "A precondição ainda requer evidência")
    assert updated.known_facts == []
    assert updated.model_validate(updated.model_dump()) == updated


def test_plan_semantics_reject_unknown_tool_and_verifier(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=True)
    plan = Plan(
        objective="Criar arquivo",
        steps=[
            PlanStep(
                id=1,
                action="Criar arquivo",
                tool="file.exists",
                arguments={"file_path": "report.txt"},
                success_condition="file_exists::report.txt",
            )
        ],
    )
    with pytest.raises(ValueError, match="ferramenta desconhecida"):
        orchestrator._validate_plan_semantics(
            {"allowed_tools": ["file.write"]},
            plan,
        )


def test_plan_semantics_reject_missing_tool_arguments(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=True)
    plan = Plan(
        objective="Criar arquivo",
        steps=[
            PlanStep(
                id=1,
                action="Criar arquivo",
                tool="file.write",
                arguments={"file_path": "report.txt"},
                success_condition="file_exists:report.txt",
            )
        ],
    )
    with pytest.raises(ValueError, match="argumentos ausentes"):
        orchestrator._validate_plan_semantics(
            {"allowed_tools": ["file.write"]},
            plan,
        )


def test_hypothesis_cannot_be_silently_promoted_to_fact() -> None:
    claim = EpistemicClaim(kind=EpistemicKind.FACT, content="arquivo existe", confidence=1.0)
    hypothesis = EpistemicClaim(kind=EpistemicKind.HYPOTHESIS, content="arquivo existe", confidence=0.5)
    with pytest.raises(ValidationError, match="hipótese"):
        EpistemicState(known_facts=[claim], hypotheses=[hypothesis], hypothesis_confidences={"arquivo existe": 0.5})


def test_claim_kind_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="known_facts"):
        EpistemicState(known_facts=[EpistemicClaim(kind=EpistemicKind.HYPOTHESIS, content="não observado")])


@pytest.mark.asyncio
async def test_epistemic_state_flag_persists_orientation_and_tool_observation(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=True)
    task = await orchestrator.create_task(
        TaskCreate(
            title="Estado epistêmico",
            objective="Registrar uma observação verificável.",
            workspace="epistemic_enabled",
            autonomy_mode=4,
            allowed_tools=["python.execute"],
            action_budget=(1, 3),
        )
    )
    orientation = OrientationSnapshot(
        mission_id=task["id"],
        observations=["workspace inicial vazio"],
        evidence_refs=["orientation:test"],
        allowed_tools=["python.execute"],
        action_budget=(1, 3),
    )
    snapshot = await orchestrator.horizon.ensure_initial_observation(task, orientation=orientation)
    assert snapshot.epistemic_state is not None
    assert snapshot.epistemic_state.known_facts[0].kind is EpistemicKind.FACT
    assert snapshot.epistemic_state.known_facts[0].content == "workspace inicial vazio"

    async def execute(_task_id: str, _call) -> dict[str, Any]:
        orchestrator.db.execute("UPDATE tasks SET tool_call_count=tool_call_count+1 WHERE id=?", (task["id"],))
        return {"status": "completed", "output": "precondição confirmada", "execution_id": "exec:test"}

    orchestrator.horizon.execute_tool = execute
    action = NextAction(
        intent="observar a precondição",
        tool="python.execute",
        arguments={"code": "print('ok')"},
        expected_evidence=VerificationSpec(type="tool_success"),
    )
    observation, updated, validation = await orchestrator.horizon.execute_iteration(task, action, snapshot)
    assert validation.accepted is True
    assert observation is not None
    assert updated.epistemic_state is not None
    assert any("precondição confirmada" in claim.content for claim in updated.epistemic_state.known_facts)
    row = orchestrator.db.one("SELECT epistemic_state_json FROM cognitive_snapshots WHERE task_id=? ORDER BY iteration DESC LIMIT 1", (task["id"],))
    assert row is not None and "precondição confirmada" in row["epistemic_state_json"]
    events = orchestrator.db.all("SELECT event_type,payload_json FROM events WHERE task_id=? AND event_type='cognition.epistemic_state.updated'", (task["id"],))
    assert events


@pytest.mark.asyncio
async def test_epistemic_state_is_absent_when_flag_is_off(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=False)
    task = await orchestrator.create_task(
        TaskCreate(title="Estado desligado", objective="Não persistir estado novo.", workspace="epistemic_disabled", autonomy_mode=4)
    )
    snapshot = await orchestrator.horizon.ensure_initial_observation(task, orientation=OrientationSnapshot(mission_id=task["id"]))
    assert snapshot.epistemic_state is None
    row = orchestrator.db.one("SELECT epistemic_state_json FROM cognitive_snapshots WHERE task_id=?", (task["id"],))
    assert row is not None and row["epistemic_state_json"] is None
    assert not orchestrator.db.all("SELECT 1 FROM events WHERE task_id=? AND event_type='cognition.epistemic_state.updated'", (task["id"],))


@pytest.mark.asyncio
async def test_epistemic_summary_feeds_real_decision_prompt(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, enabled=True)
    task = await orchestrator.create_task(
        TaskCreate(title="Prompt epistêmico", objective="Escolher uma ação verificável.", workspace="epistemic_prompt", autonomy_mode=4, allowed_tools=["python.execute"], action_budget=(1, 2))
    )
    snapshot = await orchestrator.horizon.ensure_initial_observation(
        task,
        orientation=OrientationSnapshot(mission_id=task["id"], observations=["observação inicial"]),
    )
    captured: list[list[dict[str, str]]] = []

    async def structured(_schema, messages, **_kwargs):
        captured.append(messages)
        return NextAction(intent="executar teste", tool="python.execute", arguments={"code": "print(1)"}, expected_evidence=VerificationSpec(type="tool_success"))

    orchestrator.models.structured = structured  # type: ignore[method-assign]
    await orchestrator.horizon.decide_next_action(task, snapshot)
    assert captured
    assert "Estado epistêmico estruturado" in captured[0][1]["content"]
    assert "observação inicial" in captured[0][1]["content"]
