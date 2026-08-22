from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from time import monotonic

import pytest

from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway, ModelResponse, Usage
from ultron.policy.engine import PolicyEngine
from ultron.schemas import Plan, PlanStep, TaskCreate, ToolCall
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _orchestrator(tmp_path: Path) -> Orchestrator:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["memory"]["vector_enabled"] = False
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


@pytest.mark.asyncio
async def test_planner_uses_structured_output_with_seed_and_audits_repair(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.planning_seed = 49
    captured: dict[str, object] = {}

    async def structured(schema, messages, model_name=None, **kwargs):
        captured["schema"] = schema
        captured["messages"] = messages
        captured["model_name"] = model_name
        captured["seed"] = kwargs["seed"]
        observer = kwargs["on_response"]
        for is_repair, latency_ms in ((False, 1), (True, 2)):
            await observer(
                ModelResponse(
                    content="{}",
                    tool_calls=[],
                    usage=Usage(prompt_tokens=3, output_tokens=4),
                    latency_ms=latency_ms,
                    model="qwen2.5:3b",
                    finish_reason="stop",
                    local=True,
                ),
                is_repair,
            )
        return Plan(
            objective="Planejar com reparo",
            steps=[PlanStep(id=1, action="Analisar contexto", success_condition="task_context")],
            confidence=0.8,
        )

    orchestrator.models.structured = structured  # type: ignore[method-assign]
    created = await orchestrator.create_task(
        TaskCreate(
            title="Plano reparado",
            objective="Criar um arquivo de evidência.",
            workspace="structured_repair",
            autonomy_mode=4,
        )
    )
    task = orchestrator.get_task(created["id"])
    assert task is not None

    plan = await orchestrator._make_plan(task, [])

    assert plan.confidence == 0.8
    assert captured["schema"] is Plan
    assert captured["model_name"] == orchestrator.models.primary_name
    assert captured["seed"] == 49
    assert orchestrator.plan_sources[created["id"]] == "model_structured"
    calls = orchestrator.db.all(
        "SELECT purpose,model,seed FROM model_calls WHERE task_id=? ORDER BY created_at, rowid",
        (created["id"],),
    )
    assert calls == [
        {"purpose": "planning", "model": "qwen2.5:3b", "seed": 49},
        {"purpose": "planning_repair", "model": "qwen2.5:3b", "seed": 49},
    ]
    assert orchestrator.get_task(created["id"])["llm_call_count"] == 2


def test_fallback_preserves_supervision_and_respects_e2e_allowlist(tmp_path: Path) -> None:
    task = {
        "title": "Registrar evidência",
        "objective": "Criar um arquivo de relatório no workspace.",
    }
    supervised = _orchestrator(tmp_path)
    supervised_step = next(step for step in supervised._fallback_plan(task).steps if step.tool is not None)
    assert supervised_step.tool == "file.write"
    assert supervised_step.risk.value == "R2"

    e2e_restricted = _orchestrator(tmp_path)
    e2e_restricted.tools.manifests = {
        name: manifest for name, manifest in e2e_restricted.tools.manifests.items() if name != "file.write"
    }
    benchmark_step = next(step for step in e2e_restricted._fallback_plan(task).steps if step.tool is not None)
    assert benchmark_step.tool == "python.execute"
    assert benchmark_step.risk.value == "R1"


@pytest.mark.asyncio
async def test_mission_contract_reaches_planner_and_blocks_unlisted_tool(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    captured: dict[str, object] = {}

    async def structured(schema, messages, model_name=None, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return Plan(
            objective="Plano contratado",
            steps=[PlanStep(id=1, action="Analisar contexto", success_condition="task_context")],
        )

    orchestrator.models.structured = structured  # type: ignore[method-assign]
    created = await orchestrator.create_task(
        TaskCreate(
            title="Missão contratada",
            objective="Analisar o workspace sem escrever fora do escopo.",
            workspace="mission_contract",
            autonomy_mode=4,
            allowed_tools=["file.list", "python.execute"],
            action_budget=(2, 3),
        )
    )
    task = orchestrator.get_task(created["id"])
    assert task is not None
    assert task["allowed_tools"] == ["file.list", "python.execute"]
    assert task["action_budget"] == [2, 3]

    await orchestrator._make_plan(task, [])
    assert "ferramentas autorizadas: ['file.list', 'python.execute']" in str(captured["prompt"])
    assert "orçamento de ações: [2, 3]" in str(captured["prompt"])

    blocked = await orchestrator.execute_tool(
        created["id"], ToolCall(tool_name="file.write", arguments={"path": "x.txt", "content": "x"})
    )
    assert blocked["status"] == "blocked"
    assert "contrato da missão" in blocked["error"]
    trace = orchestrator.db.one(
        "SELECT event_type FROM execution_traces WHERE task_id=? AND event_type='mission_contract.tool_blocked'",
        (created["id"],),
    )
    assert trace is not None


def test_mission_action_budget_caps_tool_calls_without_raising_global_limits(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    async def create() -> dict:
        return await orchestrator.create_task(
            TaskCreate(
                title="Orçamento estrito",
                objective="Validar o teto de chamadas permitido pela missão.",
                workspace="mission_budget",
                action_budget=(1, 1),
            )
        )

    created = asyncio.run(create())
    orchestrator.db.execute("UPDATE tasks SET tool_call_count=1 WHERE id=?", (created["id"],))
    with pytest.raises(RuntimeError, match="contrato da missão"):
        orchestrator._assert_limits(created["id"], monotonic())


def test_step_success_verifier_requires_deterministic_predicate(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    verifier = StepSuccessVerifier(orchestrator.tools)
    task = {"workspace": "verify", "objective": "Verificar contrato"}
    unknown = verifier.verify(
        PlanStep(id=1, action="Afirmar conclusão", success_condition="arquivo pronto"),
        task,
        None,
        prior_steps_verified=True,
    )
    assert not unknown.accepted
    assert unknown.basis == "sem_verificador_deterministico"
    context = verifier.verify(
        PlanStep(id=1, action="Analisar contexto", success_condition="task_context"),
        task,
        None,
        prior_steps_verified=True,
    )
    assert context.accepted


def test_orchestrator_replans_after_verifiable_failure_and_completes(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    calls = 0

    async def planned(_task, _memories, _routed=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Plan(
                objective="Recuperar artefato",
                steps=[
                    PlanStep(
                        id=1,
                        action="Executar artefato ausente",
                        tool="python.execute",
                        arguments={"code": "raise FileNotFoundError('arquivo ausente')"},
                        success_condition="tool_exit_zero",
                    )
                ],
                confidence=0.8,
            )
        return Plan(
            objective="Recuperar artefato",
            steps=[
                PlanStep(
                    id=1,
                    action="Criar artefato de recuperação",
                    tool="python.execute",
                    arguments={"code": "from pathlib import Path; Path('done.txt').write_text('done')"},
                    success_condition="file_contains:done.txt::done",
                ),
                PlanStep(id=2, action="Conferir etapas", success_condition="prior_steps_completed"),
            ],
            confidence=0.9,
        )

    orchestrator._make_plan = planned

    async def run_case() -> dict:
        created = await orchestrator.create_task(
            TaskCreate(
                title="Recuperar artefato",
                objective="Criar arquivo após falha de dependência.",
                workspace="replan_case",
                autonomy_mode=4,
            )
        )
        await orchestrator.run(created["id"])
        await orchestrator.active[created["id"]]
        return orchestrator.get_task(created["id"]) or {}

    task = asyncio.run(run_case())
    assert calls == 2
    assert task["status"] == "completed"
    assert task["replan_count"] == 1
    assert (orchestrator.tools.workspace_for("replan_case") / "done.txt").read_text() == "done"
    plans = orchestrator.db.all("SELECT revision FROM plans WHERE task_id=? ORDER BY revision", (task["id"],))
    assert [row["revision"] for row in plans] == [1, 2]
    failures = orchestrator.db.all("SELECT category FROM failures WHERE task_id=?", (task["id"],))
    assert failures


def test_orchestrator_resumes_remaining_steps_after_approval(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    async def planned(_task, _memories, _routed=None):
        return Plan(
            objective="Executar plano supervisionado completo",
            steps=[
                PlanStep(
                    id=1,
                    action="Criar arquivo aprovado",
                    tool="file.write",
                    arguments={"path": "approved.md", "content": "approved"},
                    success_condition="file_contains:approved.md::approved",
                ),
                PlanStep(
                    id=2,
                    action="Criar arquivo posterior",
                    tool="python.execute",
                    arguments={"code": "from pathlib import Path; Path('continued.txt').write_text('continued')"},
                    success_condition="file_contains:continued.txt::continued",
                ),
                PlanStep(id=3, action="Conferir sequência", success_condition="prior_steps_completed"),
            ],
            confidence=0.9,
        )

    orchestrator._make_plan = planned

    async def run_case() -> dict:
        created = await orchestrator.create_task(
            TaskCreate(
                title="Plano supervisionado",
                objective="Criar dois arquivos após aprovação.",
                workspace="approval_continue",
                autonomy_mode=2,
            )
        )
        await orchestrator.run(created["id"])
        await orchestrator.active[created["id"]]
        approval = orchestrator.db.one(
            "SELECT id FROM approvals WHERE task_id=? AND status='pending'", (created["id"],)
        )
        assert approval
        await orchestrator.decide_approval(approval["id"], True, "aprovar sequência")
        await orchestrator.active[created["id"]]
        return orchestrator.get_task(created["id"]) or {}

    task = asyncio.run(run_case())
    workspace = orchestrator.tools.workspace_for("approval_continue")
    assert task["status"] == "completed"
    assert task["step_count"] == 3
    assert (workspace / "approved.md").read_text() == "approved"
    assert (workspace / "continued.txt").read_text() == "continued"
    events = orchestrator.db.all("SELECT event_type FROM events WHERE task_id=?", (task["id"],))
    assert "task.resumed" in {event["event_type"] for event in events}


def test_continuation_survives_restart_before_approval(tmp_path: Path) -> None:
    original = _orchestrator(tmp_path)

    async def planned(_task, _memories, _routed=None):
        return Plan(
            objective="Persistir e retomar",
            steps=[
                PlanStep(
                    id=1,
                    action="Criar arquivo após aprovação",
                    tool="file.write",
                    arguments={"path": "persisted.md", "content": "persisted"},
                    success_condition="file_contains:persisted.md::persisted",
                ),
                PlanStep(id=2, action="Confirmar continuidade", success_condition="prior_steps_completed"),
            ],
            confidence=0.9,
        )

    original._make_plan = planned

    async def run_case() -> tuple[str, str]:
        created = await original.create_task(
            TaskCreate(
                title="Continuidade persistida",
                objective="Aguardar aprovação e sobreviver à reinicialização.",
                workspace="continuation_restart",
                autonomy_mode=2,
            )
        )
        await original.run(created["id"])
        await original.active[created["id"]]
        approval = original.db.one("SELECT id FROM approvals WHERE task_id=? AND status='pending'", (created["id"],))
        assert approval
        continuation = original.db.one("SELECT task_id,status FROM task_continuations WHERE task_id=?", (created["id"],))
        assert continuation == {"task_id": created["id"], "status": "waiting_approval"}
        return created["id"], approval["id"]

    task_id, approval_id = asyncio.run(run_case())
    restarted = _orchestrator(tmp_path)

    async def recover_and_approve() -> dict:
        assert await restarted.recover_continuations() == 1
        await restarted.decide_approval(approval_id, True, "aprovar após reinício")
        await restarted.active[task_id]
        return restarted.get_task(task_id) or {}

    task = asyncio.run(recover_and_approve())
    assert task["status"] == "completed"
    assert (restarted.tools.workspace_for("continuation_restart") / "persisted.md").read_text() == "persisted"
    assert restarted.db.one("SELECT task_id FROM task_continuations WHERE task_id=?", (task_id,)) is None
    traces = restarted.db.all("SELECT event_type FROM execution_traces WHERE task_id=?", (task_id,))
    assert "step_verified" in {trace["event_type"] for trace in traces}


def test_verifier_registry_rejects_shell_free_conditions_and_checks_task_contract(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    verifier = StepSuccessVerifier(orchestrator.tools)
    task = {"workspace": "verify_registry", "objective": "Verificar contrato"}
    unregistered = verifier.verify(
        PlanStep(id=1, action="Executar shell", success_condition="shell:pytest -q"),
        task,
        {"status": "completed"},
        prior_steps_verified=True,
    )
    assert not unregistered.accepted
    from ultron.core.verifier import TaskSuccessContract

    contract = verifier.verify_task_contract(
        TaskSuccessContract(("task_context", "prior_steps_completed")),
        task,
        prior_steps_verified=True,
    )
    assert contract.accepted
