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
from ultron.schemas import (
    NextAction,
    Plan,
    PlanStep,
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


@pytest.mark.asyncio
async def test_closed_loop_false_stop_persists_sanitized_feedback_before_a_different_action(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.settings.raw["cognition"]["controller_mode"] = "next_action"
    private_secret = "PRIVATE_EVALUATOR_SECRET_MUST_NOT_LEAK"
    prompts: list[str] = []
    decisions = [
        NextAction(
            intent="Propor conclusão prematura",
            expected_evidence=VerificationSpec(type="none"),
            stop=True,
            stop_reason="parece concluído",
        ),
        NextAction(
            intent="Criar evidência recuperada",
            tool="python.execute",
            arguments={"code": "create recovered artifact"},
            expected_evidence=VerificationSpec(type="tool_success"),
        ),
        NextAction(
            intent="Propor conclusão após evidência",
            expected_evidence=VerificationSpec(type="none"),
            stop=True,
            stop_reason="evidência criada",
        ),
    ]

    async def structured(schema, messages, **_kwargs):
        assert schema is NextAction
        prompts.append(messages[-1]["content"])
        return decisions.pop(0)

    async def execute_recovery_action(task_id: str, call: ToolCall) -> dict:
        assert call.tool_name == "python.execute"
        task = orchestrator.get_task(task_id)
        assert task is not None
        workspace = orchestrator.tools.workspace_for(str(task["workspace"]))
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "recovered.txt").write_text("recovered", encoding="utf-8")
        orchestrator.db.execute("UPDATE tasks SET tool_call_count=tool_call_count+1 WHERE id=?", (task_id,))
        return {"status": "completed", "output": "recovered artifact"}

    orchestrator.models.structured = structured  # type: ignore[method-assign]
    orchestrator.horizon.execute_tool = execute_recovery_action
    created = await orchestrator.create_task(
        TaskCreate(
            title="False stop sanitizado",
            objective="Criar recovered.txt após feedback externo.",
            workspace="closed_loop_feedback",
            autonomy_mode=4,
            allowed_tools=["python.execute"],
            action_budget=(1, 3),
            requires_external_outcome=True,
        )
    )

    await orchestrator.run(created["id"])
    await orchestrator.active[created["id"]]
    assert orchestrator.get_task(created["id"])["status"] == "waiting_outcome"

    failed = await orchestrator.resolve_external_outcome(
        created["id"], {"passed": False, "evidence": [private_secret]}
    )
    assert not failed.success
    await orchestrator.active[created["id"]]
    assert orchestrator.get_task(created["id"])["status"] == "waiting_outcome"
    assert len(prompts) == 3
    assert "external_feedback_attempt:1" in prompts[1]
    assert private_secret not in prompts[1]
    assert (orchestrator.tools.workspace_for("closed_loop_feedback") / "recovered.txt").read_text(encoding="utf-8") == "recovered"

    snapshots = orchestrator.db.all(
        "SELECT external_feedback_json,evidence_refs_json FROM cognitive_snapshots WHERE task_id=? ORDER BY iteration",
        (created["id"],),
    )
    assert any(
        any("external_feedback_attempt:1" in item for item in orchestrator.db.parse_json(row["external_feedback_json"], []))
        for row in snapshots
    )
    assert all(private_secret not in str(row) for row in snapshots)

    passed = await orchestrator.resolve_external_outcome(created["id"], {"passed": True, "evidence": [private_secret]})
    assert passed.success
    assert passed.evidence_refs == ["external_feedback_attempt:2"]
    assert orchestrator.get_task(created["id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_full_plan_waits_for_one_external_outcome_without_closed_loop_recovery(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    async def planned(_task, _memories, _routed=None):
        return Plan(
            objective="Concluir uma verificação interna",
            steps=[PlanStep(id=1, action="Confirmar contexto", success_condition="task_context")],
            confidence=0.8,
        )

    orchestrator._make_plan = planned
    created = await orchestrator.create_task(
        TaskCreate(
            title="Full plan com outcome externo",
            objective="Aguardar avaliação final externa uma única vez.",
            workspace="full_plan_outcome",
            autonomy_mode=4,
            requires_external_outcome=True,
        )
    )
    await orchestrator.run(created["id"])
    await orchestrator.active[created["id"]]
    assert orchestrator.get_task(created["id"])["status"] == "waiting_outcome"

    outcome = await orchestrator.resolve_external_outcome(created["id"], {"passed": False, "evidence": ["private"]})
    assert not outcome.success
    task = orchestrator.get_task(created["id"])
    assert task is not None and task["status"] == "failed"
    assert not orchestrator.active
    assert orchestrator.db.one("SELECT COUNT(*) AS count FROM plans WHERE task_id=?", (created["id"],)) == {"count": 1}


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


@pytest.mark.asyncio
@pytest.mark.parametrize("controller_mode", ("full_plan", "short_horizon", "next_action"))
async def test_all_controller_modes_accept_external_pass_as_the_final_authority(
    tmp_path: Path, controller_mode: str
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.settings.raw["cognition"]["controller_mode"] = controller_mode
    created = await orchestrator.create_task(
        TaskCreate(
            title=f"Outcome final {controller_mode}",
            objective="Concluir somente com resultado externo.",
            workspace=f"outcome_final_{controller_mode}",
            autonomy_mode=4,
            requires_external_outcome=True,
        )
    )
    orchestrator._update_task(created["id"], status=TaskStatus.WAITING_OUTCOME, error=None)

    outcome = await orchestrator.resolve_external_outcome(
        created["id"], {"passed": True, "evidence": ["PRIVATE_EVALUATOR_SECRET"]}
    )

    assert outcome.success
    assert outcome.evidence_refs == ["external_feedback_attempt:1"]
    assert orchestrator.get_task(created["id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_short_horizon_false_stop_persists_feedback_and_restarts_closed_loop(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.settings.raw["cognition"]["controller_mode"] = "short_horizon"
    restarted: list[str] = []

    async def run_again(task_id: str) -> None:
        restarted.append(task_id)

    orchestrator.run = run_again  # type: ignore[method-assign]
    created = await orchestrator.create_task(
        TaskCreate(
            title="Recuperação short horizon",
            objective="Retomar somente após feedback público.",
            workspace="short_feedback",
            autonomy_mode=4,
            requires_external_outcome=True,
        )
    )
    orchestrator._update_task(created["id"], status=TaskStatus.WAITING_OUTCOME, error=None)

    outcome = await orchestrator.resolve_external_outcome(
        created["id"], {"passed": False, "evidence": ["PRIVATE_EVALUATOR_SECRET"]}
    )

    assert not outcome.success
    assert restarted == [created["id"]]
    assert orchestrator.get_task(created["id"])["status"] == "running"
    snapshot = orchestrator.db.one(
        "SELECT external_feedback_json FROM cognitive_snapshots WHERE task_id=? ORDER BY iteration DESC LIMIT 1",
        (created["id"],),
    )
    assert snapshot is not None
    feedback = orchestrator.db.parse_json(snapshot["external_feedback_json"], [])
    assert any("external_feedback_attempt:1" in item for item in feedback)
    assert "PRIVATE_EVALUATOR_SECRET" not in str(feedback)


@pytest.mark.asyncio
async def test_external_outcome_gates_pending_experience_writeback(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    failed_task = await orchestrator.create_task(
        TaskCreate(
            title="Writeback bloqueado",
            objective="Não promover experiência após evaluator privado falhar.",
            workspace="writeback_failed",
            autonomy_mode=4,
            requires_external_outcome=True,
        )
    )
    failed_experience = orchestrator.memory.store_experience(
        failed_task["id"],
        "structured-plan",
        [],
        "Sucesso interno não autoritativo",
        True,
        [],
        ["Não reutilizar sem outcome final."],
        0.8,
    )
    orchestrator._update_task(failed_task["id"], status=TaskStatus.WAITING_OUTCOME, error=None)
    failed = await orchestrator.resolve_external_outcome(failed_task["id"], {"passed": False, "evidence": ["private-fail"]})
    assert not failed.success
    assert orchestrator.db.one("SELECT verification_state,verified_writeback_id FROM experiences WHERE id=?", (failed_experience,)) == {
        "verification_state": "pending",
        "verified_writeback_id": None,
    }
    assert orchestrator.db.one(
        "SELECT COUNT(*) AS count FROM verified_writebacks WHERE target_type='experience' AND target_id=? AND allowed=1",
        (failed_experience,),
    ) == {"count": 0}

    passed_task = await orchestrator.create_task(
        TaskCreate(
            title="Writeback aprovado",
            objective="Promover experiência somente após evaluator privado aprovar.",
            workspace="writeback_passed",
            autonomy_mode=4,
            requires_external_outcome=True,
        )
    )
    passed_experience = orchestrator.memory.store_experience(
        passed_task["id"],
        "structured-plan",
        [],
        "Sucesso interno pendente de authority",
        True,
        [],
        ["Reutilizar somente após outcome final."],
        0.8,
    )
    orchestrator._update_task(passed_task["id"], status=TaskStatus.WAITING_OUTCOME, error=None)
    passed = await orchestrator.resolve_external_outcome(passed_task["id"], {"passed": True, "evidence": ["private-pass"]})
    assert passed.success
    promoted = orchestrator.db.one(
        "SELECT verification_state,verified_writeback_id FROM experiences WHERE id=?", (passed_experience,)
    )
    assert promoted["verification_state"] == "verified"
    assert promoted["verified_writeback_id"]
    assert orchestrator.db.one(
        "SELECT COUNT(*) AS count FROM experience_signatures WHERE experience_id=? AND verified=1", (passed_experience,)
    ) == {"count": 1}
    assert orchestrator.db.one(
        "SELECT COUNT(*) AS count FROM verified_writebacks WHERE target_type='experience' AND target_id=? AND allowed=1",
        (passed_experience,),
    ) == {"count": 1}
