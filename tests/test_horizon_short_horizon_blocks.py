from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    MissionOutline,
    NextAction,
    ShortHorizonDecision,
    TaskCreate,
    TaskStatus,
    ToolCall,
    VerificationSpec,
)
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _orchestrator(tmp_path: Path) -> Orchestrator:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["memory"]["vector_enabled"] = False
    settings.raw["cognition"]["controller_mode"] = "short_horizon"
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


def _action(
    name: str, *, verification: str = "tool_success", verification_path: str | None = None, stop: bool = False
) -> NextAction:
    return NextAction(
        intent=f"executar {name}",
        tool=None if stop else "python.execute",
        arguments={} if stop else {"code": name},
        expected_evidence=VerificationSpec(type=verification, path=verification_path),
        stop=stop,
        stop_reason="conclusão proposta" if stop else None,
    )


def _block(*actions: NextAction) -> ShortHorizonDecision:
    return ShortHorizonDecision(actions=list(actions))


async def _run(orchestrator: Orchestrator, task: dict[str, Any]) -> None:
    await orchestrator.run(task["id"])
    active = orchestrator.active.get(task["id"])
    if active:
        await active


def _invalidation_payloads(orchestrator: Orchestrator, task_id: str) -> list[dict[str, Any]]:
    rows = orchestrator.db.all(
        "SELECT payload_json FROM execution_traces WHERE task_id=? AND event_type='cognition.short_horizon_block.invalidated' ORDER BY created_at,rowid",
        (task_id,),
    )
    return [orchestrator.db.parse_json(row["payload_json"], {}) for row in rows]


def _install_structured_blocks(orchestrator: Orchestrator, blocks: list[ShortHorizonDecision], schemas: list[type]) -> None:
    async def structured(schema, _messages, **_kwargs):
        if schema is MissionOutline:
            return MissionOutline(subgoals=[])
        schemas.append(schema)
        assert schema is ShortHorizonDecision
        return blocks.pop(0)

    orchestrator.models.structured = structured  # type: ignore[method-assign]


def _install_tool_executor(
    orchestrator: Orchestrator,
    executed: list[str],
    *,
    status_by_code: dict[str, str] | None = None,
    on_execute=None,
) -> None:
    status_by_code = status_by_code or {}

    async def execute(task_id: str, call: ToolCall) -> dict[str, Any]:
        code = str(call.arguments.get("code"))
        executed.append(code)
        orchestrator.db.execute("UPDATE tasks SET tool_call_count=tool_call_count+1 WHERE id=?", (task_id,))
        if on_execute is not None:
            await on_execute(task_id, code)
        status = status_by_code.get(code, "completed")
        return {"status": status, "output": code, "error": f"{code} failed" if status == "failed" else None}

    orchestrator.horizon.execute_tool = execute


@pytest.mark.asyncio
async def test_short_horizon_failure_discards_remaining_actions(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(orchestrator, [_block(_action("a1"), _action("a2"), _action("a3")), _block(_action("stop", stop=True))], schemas)
    _install_tool_executor(orchestrator, executed, status_by_code={"a1": "failed"})
    task = await orchestrator.create_task(TaskCreate(title="Falha de bloco", objective="Invalidar ações restantes.", workspace="block_failure", autonomy_mode=4, allowed_tools=["python.execute"], requires_external_outcome=True))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    invalidations = _invalidation_payloads(orchestrator, task["id"])
    assert invalidations[-1]["reason"] == "TOOL_OR_ACTION_FAILURE"
    assert invalidations[-1]["remaining_actions_discarded"] == 2
    actions = orchestrator.db.all("SELECT arguments_json FROM cognitive_actions WHERE task_id=?", (task["id"],))
    assert len(actions) == 1
    assert orchestrator.get_task(task["id"])["status"] == "waiting_outcome"


@pytest.mark.asyncio
async def test_short_horizon_verification_failure_discards_remaining_actions(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(
        orchestrator,
        [_block(_action("a1", verification="file_exists", verification_path="missing.txt"), _action("a2")), _block(_action("stop", stop=True))],
        schemas,
    )
    _install_tool_executor(orchestrator, executed)
    task = await orchestrator.create_task(TaskCreate(title="Verificação falha", objective="Descartar após verificação inválida.", workspace="block_verification", autonomy_mode=4, allowed_tools=["python.execute"], requires_external_outcome=True))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    invalidations = _invalidation_payloads(orchestrator, task["id"])
    assert invalidations[-1]["reason"] == "VERIFICATION_FAILED"
    assert invalidations[-1]["remaining_actions_discarded"] == 1


@pytest.mark.asyncio
async def test_short_horizon_waiting_approval_discards_remaining_actions(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []

    async def pause_for_approval(task_id: str, _code: str) -> None:
        orchestrator._update_task(task_id, status=TaskStatus.WAITING_APPROVAL, error=None)

    _install_structured_blocks(orchestrator, [_block(_action("a1"), _action("a2"))], schemas)
    _install_tool_executor(orchestrator, executed, status_by_code={"a1": "waiting_approval"}, on_execute=pause_for_approval)
    task = await orchestrator.create_task(TaskCreate(title="Aprovação", objective="Pausar o bloco sem executar a próxima ação.", workspace="block_approval", autonomy_mode=2, allowed_tools=["python.execute"], requires_external_outcome=True))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    assert schemas == [ShortHorizonDecision]
    assert orchestrator.get_task(task["id"])["status"] == "waiting_approval"
    invalidations = _invalidation_payloads(orchestrator, task["id"])
    assert invalidations[-1]["reason"] == "WAITING_APPROVAL"
    assert invalidations[-1]["remaining_actions_discarded"] == 1


@pytest.mark.asyncio
async def test_short_horizon_successful_block_executes_all_actions_once(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(orchestrator, [_block(_action("a1"), _action("a2"), _action("a3")), _block(_action("stop", stop=True))], schemas)
    _install_tool_executor(orchestrator, executed)
    task = await orchestrator.create_task(TaskCreate(title="Bloco válido", objective="Executar um bloco válido uma única vez.", workspace="block_success", autonomy_mode=4, allowed_tools=["python.execute"], requires_external_outcome=True, action_budget=(1, 4)))

    await _run(orchestrator, task)

    assert executed == ["a1", "a2", "a3"]
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    assert not _invalidation_payloads(orchestrator, task["id"])
    completed = orchestrator.db.one("SELECT event_type FROM execution_traces WHERE task_id=? AND event_type='cognition.short_horizon_block.completed'", (task["id"],))
    assert completed is not None


@pytest.mark.asyncio
async def test_short_horizon_budget_prevents_remaining_actions(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(orchestrator, [_block(_action("a1"), _action("a2"))], schemas)
    _install_tool_executor(orchestrator, executed)
    task = await orchestrator.create_task(TaskCreate(title="Orçamento de bloco", objective="Não exceder orçamento em bloco curto.", workspace="block_budget", autonomy_mode=4, allowed_tools=["python.execute"], action_budget=(1, 1)))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    invalidations = _invalidation_payloads(orchestrator, task["id"])
    assert invalidations[-1]["reason"] == "INSUFFICIENT_REMAINING_BUDGET"
    assert invalidations[-1]["remaining_actions_discarded"] == 1
    assert orchestrator.get_task(task["id"])["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_short_horizon_external_feedback_invalidates_pending_block(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    prompts: list[str] = []
    executed: list[str] = []

    async def structured(schema, messages, **_kwargs):
        if schema is MissionOutline:
            return MissionOutline(subgoals=[])
        schemas.append(schema)
        assert schema is ShortHorizonDecision
        prompts.append(messages[-1]["content"])
        return blocks.pop(0)

    async def add_feedback(task_id: str, _code: str) -> None:
        current = orchestrator.get_task(task_id)
        assert current is not None
        orchestrator.horizon.persist_external_feedback(current, "external_feedback_attempt:1", "feedback seguro")

    blocks = [_block(_action("a1"), _action("a2")), _block(_action("stop", stop=True))]
    orchestrator.models.structured = structured  # type: ignore[method-assign]
    _install_tool_executor(orchestrator, executed, on_execute=add_feedback)
    task = await orchestrator.create_task(TaskCreate(title="Feedback externo", objective="Descartar ação após feedback externo.", workspace="block_feedback", autonomy_mode=4, allowed_tools=["python.execute"], action_budget=(1, 3), requires_external_outcome=True))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    invalidations = _invalidation_payloads(orchestrator, task["id"])
    assert invalidations[-1]["reason"] == "EXTERNAL_FEEDBACK_CHANGED"
    assert invalidations[-1]["remaining_actions_discarded"] == 1
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    assert "external_feedback_attempt:1" in prompts[1]


@pytest.mark.asyncio
async def test_short_horizon_one_action_block_never_falls_back_to_next_action(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(orchestrator, [_block(_action("a1")), _block(_action("stop", stop=True))], schemas)
    _install_tool_executor(orchestrator, executed)
    task = await orchestrator.create_task(TaskCreate(title="Bloco unitário", objective="Solicitar novo bloco sem NextAction.", workspace="block_one_action", autonomy_mode=4, allowed_tools=["python.execute"], requires_external_outcome=True, action_budget=(1, 2)))

    await _run(orchestrator, task)

    assert executed == ["a1"]
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    assert NextAction not in schemas
    assert orchestrator.get_task(task["id"])["status"] == "waiting_outcome"


@pytest.mark.asyncio
async def test_short_horizon_never_requests_next_action_schema(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    executed: list[str] = []
    _install_structured_blocks(orchestrator, [_block(_action("a1"), _action("a2")), _block(_action("stop", stop=True))], schemas)
    _install_tool_executor(orchestrator, executed)
    task = await orchestrator.create_task(TaskCreate(title="Pureza short horizon", objective="Nunca usar schema NextAction.", workspace="block_purity", autonomy_mode=4, allowed_tools=["python.execute"], requires_external_outcome=True, action_budget=(1, 3)))

    await _run(orchestrator, task)

    assert executed == ["a1", "a2"]
    assert schemas == [ShortHorizonDecision, ShortHorizonDecision]
    assert NextAction not in schemas



def test_short_horizon_rejects_stop_before_last_action() -> None:
    with pytest.raises(ValueError, match="stop=true só é permitido na última ação"):
        _block(_action("a1"), _action("stop", stop=True), _action("a3"))


@pytest.mark.asyncio
async def test_short_horizon_stop_last_completes_block_accounting(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    schemas: list[type] = []
    _install_structured_blocks(orchestrator, [_block(_action("stop", stop=True))], schemas)
    task = await orchestrator.create_task(
        TaskCreate(
            title="Stop terminal",
            objective="Auditar uma proposta de stop terminal.",
            workspace="block_stop_terminal",
            autonomy_mode=4,
            allowed_tools=["python.execute"],
            requires_external_outcome=True,
        )
    )

    await _run(orchestrator, task)

    trace_rows = orchestrator.db.all(
        "SELECT event_type,payload_json FROM execution_traces WHERE task_id=? AND event_type LIKE 'cognition.short_horizon_block.%' ORDER BY created_at,rowid",
        (task["id"],),
    )
    events = [row["event_type"] for row in trace_rows]
    payloads = [orchestrator.db.parse_json(row["payload_json"], {}) for row in trace_rows]
    assert schemas == [ShortHorizonDecision]
    assert events == [
        "cognition.short_horizon_block.created",
        "cognition.short_horizon_block.action_executed",
        "cognition.short_horizon_block.completed",
    ]
    assert payloads[0]["actions"] == 1
    assert payloads[1]["action_index"] == 0
    assert payloads[2]["actions"] == 1
    assert not _invalidation_payloads(orchestrator, task["id"])
    assert orchestrator.get_task(task["id"])["status"] == "waiting_outcome"
