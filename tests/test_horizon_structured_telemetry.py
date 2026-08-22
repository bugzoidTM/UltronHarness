"""Testes para Horizon v0.7.1B — Universal Structured Decision Telemetry.

Garante que full_plan, short_horizon e next_action registram structured decisions
pelo mesmo mecanismo, com 1 model decision request = 1 structured_decisions row
para first attempt succeeds, repair succeeds e all repairs fail.
"""

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
from ultron.models.gateway import ModelGateway, ModelResponse, Usage
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    NextAction,
    Plan,
    PlanStep,
    ShortHorizonDecision,
    TaskCreate,
    VerificationSpec,
)
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


class MockSequenceGateway(ModelGateway):
    """Gateway que retorna uma sequência configurada de respostas por chamada."""

    def __init__(self, responses: list[str]) -> None:
        raw_settings = load_settings(ROOT).raw
        raw_settings["models"]["primary"] = "mock-seq"
        super().__init__(Settings(raw=raw_settings, root_dir=ROOT))
        self._responses = list(responses)
        self.call_count = 0

    async def generate(self, messages: list[dict[str, str]], model_name: str | None = None, **kwargs: Any) -> ModelResponse:
        if not self._responses:
            raise RuntimeError("Nenhuma resposta mock restante.")
        content = self._responses.pop(0)
        self.call_count += 1
        return ModelResponse(
            content=content,
            tool_calls=[],
            usage=Usage(prompt_tokens=10, output_tokens=10),
            latency_ms=5,
            model="mock-seq",
            finish_reason="stop",
            local=True,
        )


async def _build_env(tmp_path: Path, mode: str, gateway: ModelGateway) -> tuple[Database, Orchestrator, dict[str, Any]]:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["controller_mode"] = mode
    raw["cognition"]["controller_mode"] = mode
    raw["memory"]["vector_enabled"] = False
    raw["cognition"]["structured_repair_attempts"] = 2
    raw["security"]["require_approval_for"] = []
    settings = Settings(raw=raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    events = EventBus(db)
    tools = ToolRegistry(settings)
    policy = PolicyEngine(settings)
    orchestrator = Orchestrator(
        settings,
        db,
        events,
        MemoryService(db, settings),
        gateway,
        policy,
        tools,
        planning_seed=53,
    )
    task = await orchestrator.create_task(
        TaskCreate(
            title="Tarefa de Teste",
            objective="Criar arquivo output.txt e validar",
            workspace="ws_test",
            autonomy_mode=4,
            allowed_tools=["file.write", "file.read"],
            action_budget=[3, 5],
        )
    )
    return db, orchestrator, task


async def _run_task(orchestrator: Orchestrator, task_id: str) -> None:
    await orchestrator.run(task_id)
    active = orchestrator.active.get(task_id)
    if active:
        await active


# ===========================================================================
# 1. Full Plan Structured Decision Telemetry
# ===========================================================================


@pytest.mark.asyncio
async def test_full_plan_structured_decision_first_attempt_succeeds(tmp_path: Path) -> None:
    valid_plan = Plan(
        objective="Criar arquivo output.txt",
        steps=[PlanStep(id=1, action="Escrever", tool="file.write", arguments={"path": "output.txt", "content": "ok"}, success_condition="file_exists:output.txt")],
        risks=[],
        confidence=1.0,
    ).model_dump_json()

    gateway = MockSequenceGateway([valid_plan])
    db, orchestrator, task = await _build_env(tmp_path, "full_plan", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=?", (task["id"],))
    assert len(rows) == 1, f"Esperava exatamente 1 linha em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "full_plan"
    assert row["decision_kind"] == "plan"
    assert row["iteration"] == 1
    assert row["initial_valid"] == 1
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_full_plan_structured_decision_repair_succeeds(tmp_path: Path) -> None:
    invalid_plan = '{"objective": "invalido", "steps": "nao_e_uma_lista"}'
    valid_plan = Plan(
        objective="Criar arquivo output.txt",
        steps=[PlanStep(id=1, action="Escrever", tool="file.write", arguments={"path": "output.txt", "content": "ok"}, success_condition="file_exists:output.txt")],
        risks=[],
        confidence=1.0,
    ).model_dump_json()

    gateway = MockSequenceGateway([invalid_plan, valid_plan])
    db, orchestrator, task = await _build_env(tmp_path, "full_plan", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=?", (task["id"],))
    assert len(rows) == 1, f"Esperava 1 linha em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "full_plan"
    assert row["decision_kind"] == "plan"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 1
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_full_plan_structured_decision_all_repairs_fail_triggers_fallback(tmp_path: Path) -> None:
    invalid_1 = '{"invalido": 1}'
    invalid_2 = '{"invalido": 2}'
    invalid_3 = '{"invalido": 3}'

    gateway = MockSequenceGateway([invalid_1, invalid_2, invalid_3])
    db, orchestrator, task = await _build_env(tmp_path, "full_plan", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=?", (task["id"],))
    assert len(rows) == 1, f"Esperava 1 linha em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "full_plan"
    assert row["decision_kind"] == "plan"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 2
    assert row["validation_error_class"] == "ValidationError"
    assert orchestrator.plan_sources.get(task["id"]) == "fallback_after_model_error"


# ===========================================================================
# 2. Short Horizon Structured Decision Telemetry
# ===========================================================================


@pytest.mark.asyncio
async def test_short_horizon_structured_decision_first_attempt_succeeds(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    valid_block = ShortHorizonDecision(
        reasoning="Executar escrita",
        actions=[
            NextAction(
                intent="Gravar",
                tool="file.write",
                arguments={"path": "output.txt", "content": "ok"},
                expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
                stop=True,
                stop_reason="concluido",
            )
        ],
    ).model_dump_json()

    gateway = MockSequenceGateway([outline, valid_block])
    db, orchestrator, task = await _build_env(tmp_path, "short_horizon", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task["id"],))
    assert len(rows) == 1, f"Esperava 1 linha de short_horizon em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "short_horizon"
    assert row["decision_kind"] == "short_horizon"
    assert row["initial_valid"] == 1
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_short_horizon_structured_decision_repair_succeeds(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_block = '{"reasoning": "erro", "actions": "nao_lista"}'
    valid_block = ShortHorizonDecision(
        reasoning="Executar escrita",
        actions=[
            NextAction(
                intent="Gravar",
                tool="file.write",
                arguments={"path": "output.txt", "content": "ok"},
                expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
                stop=True,
                stop_reason="concluido",
            )
        ],
    ).model_dump_json()

    gateway = MockSequenceGateway([outline, invalid_block, valid_block])
    db, orchestrator, task = await _build_env(tmp_path, "short_horizon", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task["id"],))
    assert len(rows) == 1, f"Esperava 1 linha de short_horizon em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "short_horizon"
    assert row["decision_kind"] == "short_horizon"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 1
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_short_horizon_structured_decision_all_repairs_fail(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_1 = '{"invalido": 1}'
    invalid_2 = '{"invalido": 2}'
    invalid_3 = '{"invalido": 3}'

    gateway = MockSequenceGateway([outline, invalid_1, invalid_2, invalid_3, invalid_1, invalid_2, invalid_3, invalid_1, invalid_2, invalid_3])
    db, orchestrator, task = await _build_env(tmp_path, "short_horizon", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task["id"],))
    assert len(rows) >= 1, f"Esperava pelo menos 1 linha de short_horizon em structured_decisions, obtido {len(rows)}"
    row = rows[0]
    assert row["controller_mode"] == "short_horizon"
    assert row["decision_kind"] == "short_horizon"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 2
    assert row["validation_error_class"] == "ValidationError"


# ===========================================================================
# 3. Next Action Structured Decision Telemetry
# ===========================================================================


@pytest.mark.asyncio
async def test_next_action_structured_decision_first_attempt_succeeds(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    valid_action = NextAction(
        intent="Gravar",
        tool="file.write",
        arguments={"path": "output.txt", "content": "ok"},
        expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
        stop=True,
        stop_reason="concluido",
    ).model_dump_json()

    gateway = MockSequenceGateway([outline, valid_action])
    db, orchestrator, task = await _build_env(tmp_path, "next_action", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task["id"],))
    assert len(rows) == 1
    row = rows[0]
    assert row["controller_mode"] == "next_action"
    assert row["decision_kind"] == "next_action"
    assert row["initial_valid"] == 1
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_next_action_structured_decision_repair_succeeds(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_action = '{"intent": "sem campos obrigatorios"}'
    valid_action = NextAction(
        intent="Gravar",
        tool="file.write",
        arguments={"path": "output.txt", "content": "ok"},
        expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
        stop=True,
        stop_reason="concluido",
    ).model_dump_json()

    gateway = MockSequenceGateway([outline, invalid_action, valid_action])
    db, orchestrator, task = await _build_env(tmp_path, "next_action", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task["id"],))
    assert len(rows) == 1
    row = rows[0]
    assert row["controller_mode"] == "next_action"
    assert row["decision_kind"] == "next_action"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 1
    assert row["repair_attempts"] == 1
    assert row["validation_error_class"] is None


@pytest.mark.asyncio
async def test_next_action_structured_decision_all_repairs_fail(tmp_path: Path) -> None:
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_1 = '{"invalido": 1}'
    invalid_2 = '{"invalido": 2}'
    invalid_3 = '{"invalido": 3}'

    gateway = MockSequenceGateway([outline, invalid_1, invalid_2, invalid_3, invalid_1, invalid_2, invalid_3, invalid_1, invalid_2, invalid_3])
    db, orchestrator, task = await _build_env(tmp_path, "next_action", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task["id"],))
    assert len(rows) >= 1
    row = rows[0]
    assert row["controller_mode"] == "next_action"
    assert row["decision_kind"] == "next_action"
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 2
    assert row["validation_error_class"] == "ValidationError"


# ===========================================================================
# 4. E2E Triad SDV Telemetry Parity
# ===========================================================================


@pytest.mark.asyncio
async def test_triad_universal_structured_telemetry_across_all_modes(tmp_path: Path) -> None:
    """Verifica que full_plan, short_horizon e next_action produzem telemetria uniforme de decisões estruturadas."""
    valid_plan = Plan(
        objective="Criar arquivo output.txt",
        steps=[PlanStep(id=1, action="Escrever", tool="file.write", arguments={"path": "output.txt", "content": "ok"}, success_condition="file_exists:output.txt")],
        risks=[],
        confidence=1.0,
    ).model_dump_json()

    outline = '{"objective": "Criar arquivo output.txt", "subgoals": [{"id": 1, "description": "criar"}]}'
    valid_block = ShortHorizonDecision(
        reasoning="Executar escrita",
        actions=[
            NextAction(
                intent="Gravar",
                tool="file.write",
                arguments={"path": "output.txt", "content": "ok"},
                expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
                stop=True,
                stop_reason="concluido",
            )
        ],
    ).model_dump_json()

    valid_action = NextAction(
        intent="Gravar",
        tool="file.write",
        arguments={"path": "output.txt", "content": "ok"},
        expected_evidence=VerificationSpec(type="file_exists", path="output.txt"),
        stop=True,
        stop_reason="concluido",
    ).model_dump_json()

    # A: full_plan
    db_a, orch_a, task_a = await _build_env(tmp_path / "fp", "full_plan", MockSequenceGateway([valid_plan]))
    await _run_task(orch_a, task_a["id"])

    # B: short_horizon
    db_b, orch_b, task_b = await _build_env(tmp_path / "sh", "short_horizon", MockSequenceGateway([outline, valid_block]))
    await _run_task(orch_b, task_b["id"])

    # C: next_action
    db_c, orch_c, task_c = await _build_env(tmp_path / "na", "next_action", MockSequenceGateway([outline, valid_action]))
    await _run_task(orch_c, task_c["id"])

    dec_a = db_a.all("SELECT * FROM structured_decisions WHERE task_id=?", (task_a["id"],))
    dec_b = db_b.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task_b["id"],))
    dec_c = db_c.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task_c["id"],))

    assert len(dec_a) == 1, f"full_plan deve registrar exatamente 1 decisão, obtido {len(dec_a)}"
    assert len(dec_b) >= 1, f"short_horizon deve registrar >= 1 decisão, obtido {len(dec_b)}"
    assert len(dec_c) >= 1, f"next_action deve registrar >= 1 decisão, obtido {len(dec_c)}"

    # Todas as decisões foram registradas com a mesma semântica
    for dec_list, mode in [(dec_a, "full_plan"), (dec_b, "short_horizon"), (dec_c, "next_action")]:
        for d in dec_list:
            assert d["controller_mode"] == mode
            assert d["initial_valid"] == 1
            assert d["final_valid"] == 1
            assert d["repair_attempts"] == 0
            assert d["validation_error_class"] is None

