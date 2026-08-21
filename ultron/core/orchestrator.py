"""Orquestrador cognitivo: estados explícitos, limites, políticas, ferramentas, verificação e memória."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.core.recovery import RecoveryEngine
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.research.cycle import ExperienceCycle, SkillService
from ultron.schemas import (
    CognitiveState,
    Plan,
    PlanStep,
    RiskLevel,
    TaskCreate,
    TaskStatus,
    ToolCall,
)
from ultron.tools.registry import ToolRegistry


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        events: EventBus,
        memory: MemoryService,
        models: ModelGateway,
        policy: PolicyEngine,
        tools: ToolRegistry,
    ):
        self.settings, self.db, self.events = settings, db, events
        self.memory, self.models, self.policy, self.tools = memory, models, policy, tools
        self.recovery = RecoveryEngine()
        self.skills = SkillService(db)
        self.experience = ExperienceCycle(db, self.skills)
        self.active: dict[str, asyncio.Task[None]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}

    async def create_task(self, payload: TaskCreate) -> dict[str, Any]:
        task_id, timestamp = str(uuid4()), utcnow()
        self.tools.workspace_for(payload.workspace)
        self.db.execute(
            """INSERT INTO tasks (id,goal_id,title,objective,status,priority,workspace,autonomy_mode,created_at,updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                payload.goal_id,
                payload.title,
                payload.objective,
                TaskStatus.CREATED.value,
                payload.priority,
                payload.workspace,
                payload.autonomy_mode,
                timestamp,
                timestamp,
            ),
        )
        self.db.execute(
            "INSERT INTO task_state (task_id,state,context_json,updated_at) VALUES (?, ?, ?, ?)",
            (task_id, CognitiveState.IDLE.value, "{}", timestamp),
        )
        await self.events.emit(
            "task.created", {"title": payload.title, "objective": payload.objective}, task_id
        )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT t.*, s.state AS cognitive_state FROM tasks t LEFT JOIN task_state s ON t.id=s.task_id WHERE t.id=?",
            (task_id,),
        )
        return row

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT t.*, s.state AS cognitive_state FROM tasks t LEFT JOIN task_state s ON t.id=s.task_id ORDER BY t.updated_at DESC LIMIT ?",
            (limit,),
        )

    async def run(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise KeyError("Tarefa não encontrada.")
        if task_id in self.active and not self.active[task_id].done():
            return task
        if task["status"] in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value}:
            raise ValueError("Tarefa finalizada não pode ser retomada; crie uma nova tarefa.")
        self.cancel_events[task_id] = asyncio.Event()
        runner = asyncio.create_task(self._run_loop(task_id), name=f"ultron-task-{task_id}")
        self.active[task_id] = runner
        return self.get_task(task_id) or {}

    async def pause(self, task_id: str, reason: str = "Pausada pelo usuário.") -> None:
        event = self.cancel_events.get(task_id)
        if event:
            event.set()
        self._update_task(task_id, status=TaskStatus.PAUSED, error=reason)
        await self._transition(task_id, CognitiveState.PAUSED, {"reason": reason})
        await self.events.emit("task.paused", {"reason": reason}, task_id)

    async def cancel(self, task_id: str) -> None:
        event = self.cancel_events.get(task_id)
        if event:
            event.set()
        self._update_task(task_id, status=TaskStatus.CANCELLED, completed_at=utcnow())
        await self._transition(
            task_id, CognitiveState.CANCELLED, {"reason": "Cancelada pelo usuário."}
        )
        await self.events.emit("task.cancelled", {}, task_id)

    async def kill_all(self) -> int:
        tasks = [task_id for task_id, future in self.active.items() if not future.done()]
        for task_id in tasks:
            await self.cancel(task_id)
        return len(tasks)

    async def decide_approval(self, approval_id: str, approved: bool, note: str) -> dict[str, Any]:
        approval = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not approval or approval["status"] != "pending":
            raise KeyError("Aprovação pendente não encontrada.")
        timestamp = utcnow()
        self.db.execute(
            "UPDATE approvals SET status=?, decided_at=?, decided_by='user', decision_note=? WHERE id=?",
            ("approved" if approved else "rejected", timestamp, note, approval_id),
        )
        task_id = approval["task_id"]
        await self.events.emit(
            "approval.decided",
            {"approval_id": approval_id, "approved": approved, "note": note},
            task_id,
        )
        if approved:
            task = self.get_task(task_id)
            execution = self.db.one(
                "SELECT * FROM tool_executions WHERE id=?", (approval["tool_execution_id"],)
            )
            if not task or not execution:
                raise KeyError("Tarefa ou execução pendente não encontrada.")
            call = ToolCall(
                tool_name=approval["action"],
                arguments=self.db.parse_json(execution["arguments_json"], {}),
            )
            result = await self._execute_allowed_tool(task, execution["id"], call)
            await self._transition(
                task_id,
                CognitiveState.OBSERVE_RESULT,
                {"approved_execution": execution["id"], "ok": result["status"] == "completed"},
            )
            if result["status"] == "completed":
                self.db.execute(
                    "UPDATE tasks SET step_count=step_count+1, updated_at=? WHERE id=?",
                    (utcnow(), task_id),
                )
                await self._transition(task_id, CognitiveState.VERIFY, {"approved_execution": True})
                lessons = [f"A operação aprovada {approval['action']} foi concluída e verificada."]
                await self._transition(task_id, CognitiveState.LEARN, {"success": True})
                self.memory.store_experience(
                    task_id,
                    "approved-tool-execution",
                    [result],
                    "Tarefa concluída após aprovação do usuário.",
                    True,
                    [],
                    lessons,
                    0.9,
                )
                self._update_task(
                    task_id, status=TaskStatus.COMPLETED, completed_at=utcnow(), error=None
                )
                await self._transition(task_id, CognitiveState.COMPLETE, {"success": True})
                await self.events.emit(
                    "task.completed",
                    {"approved_execution": execution["id"], "duration_ms": result["duration_ms"]},
                    task_id,
                )
            else:
                await self._fail(task_id, str(result.get("error", "Falha após aprovação.")))
        else:
            self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                error="Ação recusada pelo usuário.",
                completed_at=timestamp,
            )
            await self._transition(task_id, CognitiveState.FAILED, {"reason": "approval_rejected"})
        return self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,)) or {}

    async def execute_tool(self, task_id: str, call: ToolCall) -> dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise KeyError("Tarefa não encontrada.")
        manifest = self.tools.get_manifest(call.tool_name)
        if not manifest:
            raise ValueError("Ferramenta desconhecida.")
        decision = self.policy.evaluate(
            call.tool_name, call.arguments, manifest.risk, int(task["autonomy_mode"])
        )
        execution_id, created_at = str(uuid4()), utcnow()
        self.db.execute(
            "INSERT INTO tool_executions (id,task_id,tool_name,arguments_json,status,risk,created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                task_id,
                call.tool_name,
                self.db.json(call.arguments),
                "requested",
                manifest.risk.value,
                created_at,
            ),
        )
        await self.events.emit(
            "tool.requested",
            {
                "execution_id": execution_id,
                "tool": call.tool_name,
                "arguments": call.arguments,
                "risk": manifest.risk.value,
            },
            task_id,
        )
        if not decision.allowed:
            self.db.execute(
                "UPDATE tool_executions SET status='blocked', error=?, completed_at=? WHERE id=?",
                (decision.rationale, utcnow(), execution_id),
            )
            await self.events.emit(
                "tool.blocked",
                {"execution_id": execution_id, "reason": decision.rationale},
                task_id,
            )
            return {"status": "blocked", "execution_id": execution_id, "error": decision.rationale}
        if decision.requires_approval:
            approval_id = str(uuid4())
            self.db.execute(
                "INSERT INTO approvals (id,task_id,tool_execution_id,action,risk,rationale,status,requested_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    approval_id,
                    task_id,
                    execution_id,
                    call.tool_name,
                    manifest.risk.value,
                    decision.rationale,
                    utcnow(),
                ),
            )
            self.db.execute(
                "UPDATE tool_executions SET status='waiting_approval' WHERE id=?", (execution_id,)
            )
            self._update_task(task_id, status=TaskStatus.WAITING_APPROVAL)
            await self.events.emit(
                "approval.required",
                {
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "tool": call.tool_name,
                    "reason": decision.rationale,
                },
                task_id,
            )
            return {
                "status": "waiting_approval",
                "execution_id": execution_id,
                "approval_id": approval_id,
            }
        return await self._execute_allowed_tool(task, execution_id, call)

    async def _execute_allowed_tool(
        self, task: dict[str, Any], execution_id: str, call: ToolCall
    ) -> dict[str, Any]:
        self.db.execute("UPDATE tool_executions SET status='running' WHERE id=?", (execution_id,))
        result = await self.tools.execute(call.tool_name, call.arguments, task["workspace"])
        status = "completed" if result.ok else "failed"
        self.db.execute(
            "UPDATE tool_executions SET status=?, output=?, error=?, duration_ms=?, completed_at=? WHERE id=?",
            (status, result.output, result.error, result.duration_ms, utcnow(), execution_id),
        )
        self.db.execute(
            "UPDATE tasks SET tool_call_count=tool_call_count+1, updated_at=? WHERE id=?",
            (utcnow(), task["id"]),
        )
        payload = {
            "execution_id": execution_id,
            "tool": call.tool_name,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }
        await self.events.emit("tool.completed", payload, task["id"])
        return {"status": status, **payload}

    async def _run_loop(self, task_id: str) -> None:
        started = monotonic()
        errors: list[str] = []
        actions: list[dict[str, Any]] = []
        try:
            task = self.get_task(task_id)
            if not task:
                return
            self._update_task(
                task_id,
                status=TaskStatus.PLANNING,
                started_at=task["started_at"] or utcnow(),
                error=None,
            )
            await self.events.emit("task.started", {"title": task["title"]}, task_id)
            await self._transition(task_id, CognitiveState.OBSERVE, {})
            await self._transition(
                task_id, CognitiveState.UNDERSTAND, {"objective": task["objective"]}
            )
            await self._transition(task_id, CognitiveState.RETRIEVE_MEMORY, {})
            memories = self.memory.search(
                __import__("ultron.schemas", fromlist=["MemorySearch"]).MemorySearch(
                    query=task["objective"], task_id=task_id, limit=8
                )
            )
            await self.events.emit(
                "memory.retrieved",
                {
                    "count": len(memories),
                    "memories": [
                        {"id": item["id"], "summary": item["summary"], "score": item.get("score")}
                        for item in memories
                    ],
                },
                task_id,
            )
            await self._transition(
                task_id, CognitiveState.DELIBERATE, {"memory_count": len(memories)}
            )
            plan = await self._make_plan(task, memories)
            self._save_plan(task_id, plan)
            await self._transition(
                task_id,
                CognitiveState.PLAN,
                {"steps": len(plan.steps), "confidence": plan.confidence},
            )
            await self.events.emit("plan.created", plan.model_dump(mode="json"), task_id)
            self._update_task(task_id, status=TaskStatus.RUNNING, confidence=plan.confidence)
            for step in plan.steps:
                self._assert_limits(task_id, started)
                if self._cancelled(task_id):
                    return
                await self._transition(
                    task_id, CognitiveState.POLICY_CHECK, {"step": step.id, "action": step.action}
                )
                await self.events.emit("task.step", {"step": step.model_dump(mode="json")}, task_id)
                if step.tool:
                    await self._transition(
                        task_id, CognitiveState.ACT, {"step": step.id, "tool": step.tool}
                    )
                    result = await self.execute_tool(
                        task_id, ToolCall(tool_name=step.tool, arguments=step.arguments)
                    )
                    actions.append(result)
                    if result["status"] == "waiting_approval":
                        await self._transition(
                            task_id,
                            CognitiveState.PAUSED,
                            {"reason": "waiting_approval", "step": step.id},
                        )
                        return
                    await self._transition(
                        task_id,
                        CognitiveState.OBSERVE_RESULT,
                        {"step": step.id, "ok": result["status"] == "completed"},
                    )
                    if result["status"] != "completed":
                        error = str(result.get("error", "Falha de ferramenta."))
                        errors.append(error)
                        failure = self.recovery.classify(error, step.tool, len(errors))
                        recovery = self.recovery.propose(failure, self.settings.limits["max_replans"])
                        self.recovery.persist(self.db, task_id, failure, recovery)
                        await self.events.emit(
                            "failure.classified",
                            {"category": failure.category.value, "recoverable": failure.recoverable, "strategy": recovery.strategy},
                            task_id,
                        )
                        if not recovery.retry or not await self._replan(task_id, task, plan, step, errors):
                            return
                else:
                    actions.append(
                        {
                            "step": step.id,
                            "action": step.action,
                            "status": "completed",
                            "evidence": step.success_condition,
                        }
                    )
                self.db.execute(
                    "UPDATE tasks SET step_count=step_count+1, updated_at=? WHERE id=?",
                    (utcnow(), task_id),
                )
            await self._transition(
                task_id, CognitiveState.VERIFY, {"actions": len(actions), "errors": len(errors)}
            )
            success = not errors
            lessons = [
                "O plano foi concluído com verificação operacional."
                if success
                else f"A execução encontrou: {errors[-1]}"
            ]
            await self._transition(task_id, CognitiveState.LEARN, {"success": success})
            self.memory.store_experience(
                task_id,
                "structured-plan",
                actions,
                "Tarefa concluída" if success else "Tarefa falhou",
                success,
                errors,
                lessons,
                0.85 if success else 0.3,
            )
            experience = self.experience.consolidate(
                task["objective"],
                "Tarefa concluída" if success else "Tarefa falhou",
                lessons,
                success,
                novel_failure=bool(errors),
            )
            await self.events.emit(
                "memory.created", {"type": "episodic", "success": success, "experience": experience}, task_id
            )
            if success:
                self._update_task(
                    task_id, status=TaskStatus.COMPLETED, completed_at=utcnow(), error=None
                )
                await self._transition(task_id, CognitiveState.COMPLETE, {"success": True})
                await self.events.emit(
                    "task.completed", {"duration_ms": int((monotonic() - started) * 1000)}, task_id
                )
            else:
                self._update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    completed_at=utcnow(),
                    error="; ".join(errors[-3:]),
                )
                await self._transition(task_id, CognitiveState.FAILED, {"errors": errors})
                await self.events.emit("task.failed", {"errors": errors}, task_id)
        except RuntimeError as exc:
            if str(exc) == "TASK_CANCELLED":
                return
            await self._fail(task_id, str(exc))
        except Exception as exc:
            await self._fail(task_id, f"Erro não tratado do orquestrador: {exc}")
        finally:
            self.active.pop(task_id, None)

    async def _make_plan(self, task: dict[str, Any], memories: list[dict[str, Any]]) -> Plan:
        prompt = [
            {
                "role": "system",
                "content": "Você é o planejador do UltronPro. Retorne estritamente JSON: objective, steps[{id,action,tool,arguments,success_condition,risk}], risks, confidence. Use somente ferramentas fornecidas quando indispensáveis.",
            },
            {
                "role": "user",
                "content": f"Objetivo: {task['objective']}\nWorkspace: {task['workspace']}\nMemórias relevantes: {[m['summary'] for m in memories]}\nFerramentas: {[m['name'] for m in self.tools.list_manifests()]}.",
            },
        ]
        try:
            response = await self.models.generate(prompt, json_mode=True)
            self.db.execute(
                "INSERT INTO model_calls (id,task_id,provider,model,purpose,latency_ms,prompt_tokens,output_tokens,finish_reason,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    task["id"],
                    "local",
                    response.model,
                    "planning",
                    response.latency_ms,
                    response.usage.prompt_tokens,
                    response.usage.output_tokens,
                    response.finish_reason,
                    utcnow(),
                ),
            )
            self.db.execute(
                "UPDATE tasks SET llm_call_count=llm_call_count+1 WHERE id=?", (task["id"],)
            )
            return Plan.model_validate_json(response.content)
        except Exception:
            return self._fallback_plan(task)

    def _fallback_plan(self, task: dict[str, Any]) -> Plan:
        objective = task["objective"].lower()
        steps = [
            PlanStep(
                id=1,
                action="Analisar objetivo e limites do workspace",
                success_condition="Objetivo registrado e limites conhecidos.",
            )
        ]
        if any(token in objective for token in ("arquivo", "document", "relatório", "relatorio")):
            steps.append(
                PlanStep(
                    id=2,
                    action="Criar registro inicial no workspace",
                    tool="file.write",
                    arguments={
                        "path": "ultron_task_note.md",
                        "content": f"# {task['title']}\n\n{task['objective']}\n",
                    },
                    success_condition="Arquivo de trabalho criado.",
                    risk=RiskLevel.R2,
                )
            )
        steps.append(
            PlanStep(
                id=len(steps) + 1,
                action="Verificar conclusão operacional",
                success_condition="Plano, eventos e experiência foram persistidos.",
            )
        )
        return Plan(
            objective=task["objective"],
            steps=steps,
            risks=["Modo determinístico ativo se nenhum LLM local estiver disponível."],
            confidence=0.55,
        )

    async def _replan(
        self,
        task_id: str,
        task: dict[str, Any],
        plan: Plan,
        failed_step: PlanStep,
        errors: list[str],
    ) -> bool:
        row = self.get_task(task_id) or task
        if int(row["replan_count"]) >= self.settings.limits["max_replans"]:
            return False
        self.db.execute(
            "UPDATE tasks SET replan_count=replan_count+1, updated_at=? WHERE id=?",
            (utcnow(), task_id),
        )
        await self._transition(
            task_id, CognitiveState.REFLECT, {"failed_step": failed_step.id, "error": errors[-1]}
        )
        await self.events.emit(
            "task.reflect",
            {
                "failed_step": failed_step.id,
                "lesson": "A ferramenta falhou; o plano deve ser revisto.",
            },
            task_id,
        )
        await self._transition(
            task_id, CognitiveState.REPLAN, {"revision": int(row["replan_count"]) + 1}
        )
        return False  # segurança: novas ações só são propostas em uma nova execução explícita

    def _save_plan(self, task_id: str, plan: Plan) -> None:
        existing = self.db.one(
            "SELECT COALESCE(MAX(revision), 0) AS max_revision FROM plans WHERE task_id=?",
            (task_id,),
        )
        revision = int(existing["max_revision"]) + 1 if existing else 1
        self.db.execute(
            "INSERT INTO plans (id,task_id,revision,objective,steps_json,risks_json,confidence,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                task_id,
                revision,
                plan.objective,
                self.db.json([step.model_dump(mode="json") for step in plan.steps]),
                self.db.json(plan.risks),
                plan.confidence,
                utcnow(),
            ),
        )

    async def _transition(
        self, task_id: str, state: CognitiveState, context: dict[str, Any]
    ) -> None:
        self.db.execute(
            "UPDATE task_state SET state=?, context_json=?, updated_at=? WHERE task_id=?",
            (state.value, self.db.json(context), utcnow(), task_id),
        )
        await self.events.emit("task.state", {"state": state.value, "context": context}, task_id)

    async def _fail(self, task_id: str, error: str) -> None:
        self._update_task(task_id, status=TaskStatus.FAILED, error=error, completed_at=utcnow())
        await self._transition(task_id, CognitiveState.FAILED, {"error": error})
        await self.events.emit("task.failed", {"error": error}, task_id)

    def _update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        error: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        updates, values = ["updated_at=?"], [utcnow()]
        if status is not None:
            updates.append("status=?")
            values.append(status.value)
        if error is not None or status in {
            TaskStatus.COMPLETED,
            TaskStatus.RUNNING,
            TaskStatus.PLANNING,
        }:
            updates.append("error=?")
            values.append(error)
        if confidence is not None:
            updates.append("confidence=?")
            values.append(confidence)
        if started_at is not None:
            updates.append("started_at=?")
            values.append(started_at)
        if completed_at is not None:
            updates.append("completed_at=?")
            values.append(completed_at)
        values.append(task_id)
        self.db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", tuple(values))

    def _assert_limits(self, task_id: str, started: float) -> None:
        task = self.get_task(task_id)
        if not task:
            raise RuntimeError("Tarefa não encontrada.")
        if self._cancelled(task_id):
            raise RuntimeError("TASK_CANCELLED")
        if monotonic() - started > self.settings.limits["max_runtime_seconds"]:
            raise RuntimeError("Tempo máximo da tarefa excedido.")
        if int(task["step_count"]) >= self.settings.limits["max_steps"]:
            raise RuntimeError("Limite de etapas excedido.")
        if int(task["tool_call_count"]) >= self.settings.limits["max_tool_calls"]:
            raise RuntimeError("Limite de chamadas de ferramenta excedido.")
        if int(task["llm_call_count"]) >= self.settings.limits["max_llm_calls"]:
            raise RuntimeError("Limite de chamadas ao modelo excedido.")

    def _cancelled(self, task_id: str) -> bool:
        return self.cancel_events.get(task_id, asyncio.Event()).is_set()
