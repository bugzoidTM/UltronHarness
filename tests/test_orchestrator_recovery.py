from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import Plan, PlanStep, TaskCreate
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _orchestrator(tmp_path: Path) -> Orchestrator:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
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
