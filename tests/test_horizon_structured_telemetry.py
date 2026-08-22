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


class MockFailingGateway(ModelGateway):
    """Gateway que falha com exceção de provider após N respostas bem-sucedidas.

    fail_after_n_calls=0 → falha na primeira chamada generate().
    fail_after_n_calls=1 → primeira chamada OK, segunda falha (simula erro durante repair).
    """

    def __init__(self, responses_before_failure: list[str], error: Exception | None = None) -> None:
        raw_settings = load_settings(ROOT).raw
        raw_settings["models"]["primary"] = "mock-fail"
        super().__init__(Settings(raw=raw_settings, root_dir=ROOT))
        self._responses = list(responses_before_failure)
        self._error = error or ConnectionError("provider unavailable")
        self.call_count = 0

    async def generate(self, messages: list[dict[str, str]], model_name: str | None = None, **kwargs: Any) -> ModelResponse:
        if self._responses:
            content = self._responses.pop(0)
            self.call_count += 1
            return ModelResponse(
                content=content,
                tool_calls=[],
                usage=Usage(prompt_tokens=10, output_tokens=10),
                latency_ms=5,
                model="mock-fail",
                finish_reason="stop",
                local=True,
            )
        self.call_count += 1
        raise self._error


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
            requires_external_outcome=True,
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


# ===========================================================================
# 5. Generation / Provider Error Telemetry
#    Verifica que exceções de provider (timeout, connection error) produzem
#    exatamente 1 structured_decisions row com error_category=GENERATION_ERROR,
#    sem confundir com erro de validação Pydantic.
# ===========================================================================


@pytest.mark.asyncio
async def test_full_plan_generation_error_first_attempt(tmp_path: Path) -> None:
    """Provider falha na primeira chamada generate() durante _make_plan."""
    gateway = MockFailingGateway([], error=ConnectionError("ollama crash"))
    db, orchestrator, task = await _build_env(tmp_path, "full_plan", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='plan'", (task["id"],))
    assert len(rows) == 1, f"Esperava exatamente 1 row para generation error, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] == "ConnectionError"
    assert row["error_category"] == "GENERATION_ERROR"


@pytest.mark.asyncio
async def test_full_plan_generation_error_during_repair(tmp_path: Path) -> None:
    """Validação falha na primeira tentativa; provider falha na segunda (durante repair)."""
    invalid_json = '{"invalido": 1}'
    gateway = MockFailingGateway([invalid_json], error=TimeoutError("read timeout"))
    db, orchestrator, task = await _build_env(tmp_path, "full_plan", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='plan'", (task["id"],))
    assert len(rows) == 1, f"Esperava exatamente 1 row, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 1
    assert row["validation_error_class"] == "TimeoutError"
    assert row["error_category"] == "GENERATION_ERROR"


@pytest.mark.asyncio
async def test_short_horizon_generation_error_first_attempt(tmp_path: Path) -> None:
    """Provider falha na primeira chamada generate() em decide_short_horizon."""
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    gateway = MockFailingGateway([outline], error=ConnectionError("provider down"))
    db, orchestrator, task = await _build_env(tmp_path, "short_horizon", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task["id"],))
    assert len(rows) >= 1, f"Esperava >= 1 row para generation error, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] == "ConnectionError"
    assert row["error_category"] == "GENERATION_ERROR"
    # Todas as rows devem ser GENERATION_ERROR (iterações re-tentadas pelo controller)
    assert all(r["error_category"] == "GENERATION_ERROR" for r in rows)


@pytest.mark.asyncio
async def test_short_horizon_generation_error_during_repair(tmp_path: Path) -> None:
    """Validação falha; provider falha na repair attempt."""
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_block = '{"invalido": 1}'
    gateway = MockFailingGateway([outline, invalid_block], error=TimeoutError("timeout"))
    db, orchestrator, task = await _build_env(tmp_path, "short_horizon", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='short_horizon'", (task["id"],))
    assert len(rows) >= 1, f"Esperava >= 1 row, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["validation_error_class"] in ("TimeoutError", "ValidationError")
    assert row["error_category"] in ("GENERATION_ERROR", "VALIDATION_ERROR")
    # Pelo menos uma row deve ser GENERATION_ERROR (a que capturou o erro de provider)
    assert any(r["error_category"] == "GENERATION_ERROR" for r in rows)


@pytest.mark.asyncio
async def test_next_action_generation_error_first_attempt(tmp_path: Path) -> None:
    """Provider falha na primeira chamada generate() em decide_next_action."""
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    gateway = MockFailingGateway([outline], error=OSError("connection reset"))
    db, orchestrator, task = await _build_env(tmp_path, "next_action", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task["id"],))
    assert len(rows) >= 1, f"Esperava >= 1 row para generation error, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["repair_attempts"] == 0
    assert row["validation_error_class"] == "OSError"
    assert row["error_category"] == "GENERATION_ERROR"
    assert all(r["error_category"] == "GENERATION_ERROR" for r in rows)


@pytest.mark.asyncio
async def test_next_action_generation_error_during_repair(tmp_path: Path) -> None:
    """Validação falha; provider falha na repair attempt."""
    outline = '{"objective": "teste", "subgoals": [{"id": 1, "description": "criar"}]}'
    invalid_action = '{"invalido": 1}'
    gateway = MockFailingGateway([outline, invalid_action], error=TimeoutError("read timeout"))
    db, orchestrator, task = await _build_env(tmp_path, "next_action", gateway)

    await _run_task(orchestrator, task["id"])

    rows = db.all("SELECT * FROM structured_decisions WHERE task_id=? AND decision_kind='next_action'", (task["id"],))
    assert len(rows) >= 1, f"Esperava >= 1 row, obtido {len(rows)}"
    row = rows[0]
    assert row["initial_valid"] == 0
    assert row["final_valid"] == 0
    assert row["validation_error_class"] in ("TimeoutError", "ValidationError")
    assert row["error_category"] in ("GENERATION_ERROR", "VALIDATION_ERROR")
    assert any(r["error_category"] == "GENERATION_ERROR" for r in rows)


# ===========================================================================
# 6. Error Category Discrimination
#    Verifica que validation errors e generation errors coexistem com
#    error_category distinto, sem confundir as causas.
# ===========================================================================


@pytest.mark.asyncio
async def test_error_category_distinguishes_validation_from_generation(tmp_path: Path) -> None:
    """Valida que validation errors recebem VALIDATION_ERROR e generation errors recebem GENERATION_ERROR."""
    # Todas as tentativas falham com validação → VALIDATION_ERROR
    invalid_1 = '{"invalido": 1}'
    invalid_2 = '{"invalido": 2}'
    invalid_3 = '{"invalido": 3}'
    gateway_val = MockSequenceGateway([invalid_1, invalid_2, invalid_3])
    db_val, orch_val, task_val = await _build_env(tmp_path / "val", "full_plan", gateway_val)
    await _run_task(orch_val, task_val["id"])

    rows_val = db_val.all("SELECT * FROM structured_decisions WHERE task_id=?", (task_val["id"],))
    assert len(rows_val) == 1
    assert rows_val[0]["error_category"] == "VALIDATION_ERROR"
    assert rows_val[0]["validation_error_class"] == "ValidationError"

    # Provider falha na primeira tentativa → GENERATION_ERROR
    gateway_gen = MockFailingGateway([], error=ConnectionError("boom"))
    db_gen, orch_gen, task_gen = await _build_env(tmp_path / "gen", "full_plan", gateway_gen)
    await _run_task(orch_gen, task_gen["id"])

    rows_gen = db_gen.all("SELECT * FROM structured_decisions WHERE task_id=?", (task_gen["id"],))
    assert len(rows_gen) == 1
    assert rows_gen[0]["error_category"] == "GENERATION_ERROR"
    assert rows_gen[0]["validation_error_class"] == "ConnectionError"

    # Sucesso → sem error_category
    valid_plan = Plan(
        objective="Criar arquivo output.txt",
        steps=[PlanStep(id=1, action="Escrever", tool="file.write", arguments={"path": "output.txt", "content": "ok"}, success_condition="file_exists:output.txt")],
        risks=[],
        confidence=1.0,
    ).model_dump_json()
    gateway_ok = MockSequenceGateway([valid_plan])
    db_ok, orch_ok, task_ok = await _build_env(tmp_path / "ok", "full_plan", gateway_ok)
    await _run_task(orch_ok, task_ok["id"])

    rows_ok = db_ok.all("SELECT * FROM structured_decisions WHERE task_id=?", (task_ok["id"],))
    assert len(rows_ok) == 1
    assert rows_ok[0]["error_category"] is None
    assert rows_ok[0]["validation_error_class"] is None


# ===========================================================================
# 7. SQLite Migration for Existing / Persistent Databases
# ===========================================================================


def test_legacy_database_migration_adds_error_category_column(tmp_path: Path) -> None:
    """Garante que bancos legados criados sem a coluna error_category são migrados com sucesso ao rodar Database.initialize()."""
    import sqlite3

    from ultron.db import SCHEMA

    db_path = tmp_path / "legacy.db"

    # 1. Cria esquema legado exato do commit v0.7.1B (SCHEMA completo, mas structured_decisions sem error_category)
    legacy_schema = SCHEMA.replace("    error_category TEXT,\n", "")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_schema)
        # Insere uma tarefa e uma decisão antiga sem error_category
        conn.execute(
            """
            INSERT INTO tasks (id, title, objective, workspace, status, autonomy_mode, priority, created_at, updated_at)
            VALUES ('t1', 'Tarefa Antiga', 'Objetivo', 'ws', 'completed', 4, 3, '2026-08-20T00:00:00Z', '2026-08-20T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO structured_decisions (id, task_id, controller_mode, decision_kind, iteration, initial_valid, final_valid, repair_attempts, validation_error_class, model, seed, created_at)
            VALUES ('d1', 't1', 'full_plan', 'plan', 1, 1, 1, 0, NULL, 'test-model', 53, '2026-08-20T00:00:00Z')
            """
        )
        conn.commit()

    # 2. Roda Database.initialize() no banco legado
    db = Database(db_path)
    db.initialize()

    # 3. Verifica que a coluna error_category agora existe no schema
    with db.connect() as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(structured_decisions)")}
        assert "error_category" in columns, "A coluna error_category não foi adicionada pela migração!"

    # 4. Verifica que a linha pré-existente foi preservada e possui error_category=None
    old_row = db.one("SELECT * FROM structured_decisions WHERE id='d1'")
    assert old_row is not None
    assert old_row["id"] == "d1"
    assert old_row["error_category"] is None
    assert old_row["initial_valid"] == 1

    # 5. Verifica que novos INSERTs com error_category ("GENERATION_ERROR", "VALIDATION_ERROR") funcionam perfeitamente
    db.execute(
        """
        INSERT INTO structured_decisions (id, task_id, controller_mode, decision_kind, iteration, initial_valid, final_valid, repair_attempts, validation_error_class, error_category, model, seed, created_at)
        VALUES ('d2', 't1', 'full_plan', 'plan', 2, 0, 0, 0, 'ConnectionError', 'GENERATION_ERROR', 'test-model', 53, '2026-08-22T00:00:00Z')
        """
    )
    new_row = db.one("SELECT * FROM structured_decisions WHERE id='d2'")
    assert new_row is not None
    assert new_row["error_category"] == "GENERATION_ERROR"
    assert new_row["validation_error_class"] == "ConnectionError"

