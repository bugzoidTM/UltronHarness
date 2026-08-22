"""Orquestrador cognitivo: estados explícitos, limites, políticas, ferramentas, verificação e memória."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.cognition.progress import ProgressTracker
from ultron.cognition.task_signature import TaskSignature
from ultron.configuration import Settings
from ultron.core.continuations import ContinuationStore
from ultron.core.events import EventBus
from ultron.core.receding_controller import RecedingHorizonController
from ultron.core.recovery import RecoveryEngine
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.learning.context_builder import ContextBuild, ContextBuilder
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.research.cycle import ExperienceCycle, SkillService
from ultron.schemas import (
    CognitiveState,
    OrientationSnapshot,
    OutcomeResult,
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
        planning_seed: int | None = None,
    ):
        self.settings, self.db, self.events = settings, db, events
        self.memory, self.models, self.policy, self.tools = memory, models, policy, tools
        self.planning_seed = planning_seed
        self.recovery = RecoveryEngine()
        self.verifier = StepSuccessVerifier(tools)
        self.horizon = RecedingHorizonController(
            settings,
            db,
            events,
            models,
            tools,
            self.verifier,
            self.execute_tool,
            planning_seed=planning_seed,
        )
        self.context_builder = ContextBuilder(db)
        self.continuations = ContinuationStore(db)
        self.skills = SkillService(db)
        self.experience = ExperienceCycle(db, self.skills)
        self.active: dict[str, asyncio.Task[None]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.suspended: dict[str, dict[str, Any]] = {}  # Compatibilidade temporária; a fonte de verdade é SQLite.
        self.plan_sources: dict[str, str] = {}
        self.task_orientations: dict[str, OrientationSnapshot] = {}

    def inject_orientation(self, task_id: str, orientation: OrientationSnapshot) -> None:
        """Injeta uma OrientationSnapshot congelada para a tarefa especificada."""
        self.task_orientations[str(task_id)] = orientation

    @staticmethod
    def _serialize_context(context: ContextBuild) -> dict[str, Any]:
        return {
            "task_signature": context.task_signature.model_dump(mode="json"),
            "task_signature_id": context.task_signature_id,
            "routed_procedures": context.routed_procedures,
            "routing_decision_ids": context.routing_decision_ids,
            "candidate_count": context.candidate_count,
            "prefilter_count": context.prefilter_count,
        }

    @staticmethod
    def _restore_context(payload: dict[str, Any]) -> ContextBuild:
        return ContextBuild(
            TaskSignature.model_validate(payload["task_signature"]),
            str(payload["task_signature_id"]),
            [str(item) for item in payload.get("routed_procedures", [])],
            [str(item) for item in payload.get("routing_decision_ids", [])],
            int(payload.get("candidate_count", 0)),
            int(payload.get("prefilter_count", 0)),
        )

    def _trace(
        self,
        task_id: str,
        event_type: str,
        *,
        revision: int | None = None,
        step_id: int | None = None,
        evidence: list[dict[str, Any]] | None = None,
        router_decision_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO execution_traces (id,execution_trace_id,task_id,plan_revision,step_id,event_type,evidence_json,router_decision_ids_json,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                f"trace-{task_id}",
                task_id,
                revision,
                step_id,
                event_type,
                self.db.json(evidence or []),
                self.db.json(router_decision_ids or []),
                self.db.json(payload or {}),
                utcnow(),
            ),
        )

    async def create_task(self, payload: TaskCreate) -> dict[str, Any]:
        task_id, timestamp = str(uuid4()), utcnow()
        self.tools.workspace_for(payload.workspace)
        action_budget = payload.action_budget
        self.db.execute(
            """INSERT INTO tasks (id,goal_id,title,objective,status,priority,workspace,autonomy_mode,allowed_tools_json,action_budget_min,action_budget_max,requires_external_outcome,created_at,updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                payload.goal_id,
                payload.title,
                payload.objective,
                TaskStatus.CREATED.value,
                payload.priority,
                payload.workspace,
                payload.autonomy_mode,
                self.db.json(payload.allowed_tools) if payload.allowed_tools is not None else None,
                action_budget[0] if action_budget else None,
                action_budget[1] if action_budget else None,
                int(payload.requires_external_outcome),
                timestamp,
                timestamp,
            ),
        )
        self.db.execute(
            "INSERT INTO task_state (task_id,state,context_json,updated_at) VALUES (?, ?, ?, ?)",
            (task_id, CognitiveState.IDLE.value, "{}", timestamp),
        )
        contract = {
            "allowed_tools": payload.allowed_tools,
            "action_budget": list(action_budget) if action_budget else None,
            "requires_external_outcome": payload.requires_external_outcome,
        }
        await self.events.emit(
            "task.created", {"title": payload.title, "objective": payload.objective, "mission_contract": contract}, task_id
        )
        self._trace(task_id, "mission_contract.bound", payload=contract)
        return self.get_task(task_id) or {}

    def _hydrate_task_contract(self, task: dict[str, Any]) -> dict[str, Any]:
        raw_tools = task.pop("allowed_tools_json", None)
        task["allowed_tools"] = self.db.parse_json(raw_tools, None) if raw_tools is not None else None
        minimum, maximum = task.pop("action_budget_min", None), task.pop("action_budget_max", None)
        task["action_budget"] = [int(minimum), int(maximum)] if minimum is not None and maximum is not None else None
        task["requires_external_outcome"] = bool(task.pop("requires_external_outcome", 0))
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT t.*, s.state AS cognitive_state FROM tasks t LEFT JOIN task_state s ON t.id=s.task_id WHERE t.id=?",
            (task_id,),
        )
        return self._hydrate_task_contract(row) if row else None

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT t.*, s.state AS cognitive_state FROM tasks t LEFT JOIN task_state s ON t.id=s.task_id ORDER BY t.updated_at DESC LIMIT ?",
            (limit,),
        )
        return [self._hydrate_task_contract(row) for row in rows]

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

    async def recover_continuations(self) -> int:
        """Restaura a visibilidade de pausas persistidas; nunca reaplica uma ação pendente."""
        recovered = 0
        for continuation in self.continuations.recoverable():
            approval = self.db.one("SELECT status FROM approvals WHERE id=?", (continuation["approval_id"],))
            task = self.get_task(str(continuation["task_id"]))
            if not approval or not task or approval["status"] != "pending":
                continue
            self._update_task(str(continuation["task_id"]), status=TaskStatus.WAITING_APPROVAL)
            await self._transition(
                str(continuation["task_id"]),
                CognitiveState.PAUSED,
                {"reason": "recovered_waiting_approval", "revision": continuation["plan_revision"], "index": continuation["step_index"]},
            )
            await self.events.emit("task.continuation_recovered", {"approval_id": continuation["approval_id"]}, str(continuation["task_id"]))
            recovered += 1
        return recovered

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
            continuation = self.continuations.load(str(task_id), approval_id)
            if continuation is None:
                await self._fail(task_id, "Continuação aprovada indisponível; a tarefa não pode ser retomada com segurança.")
                return self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,)) or {}
            self.continuations.mark_resuming(str(task_id))
            result = await self._execute_allowed_tool(task, execution["id"], call)
            payload = continuation["payload"]
            plan = Plan.model_validate(payload["plan"])
            routed_context = self._restore_context(payload["routed_context"])
            self._update_task(str(task_id), status=TaskStatus.RUNNING, error=None)

            async def resume() -> None:
                try:
                    await self._execute_plan(
                        str(task_id),
                        task,
                        plan,
                        int(continuation["plan_revision"]),
                        int(continuation["step_index"]),
                        list(payload.get("actions", [])),
                        list(payload.get("errors", [])),
                        routed_context,
                        monotonic(),
                        list(payload.get("memories", [])),
                        pending_result=result,
                    )
                except Exception as exc:
                    await self._fail(str(task_id), f"Erro ao retomar após aprovação: {exc}")
                finally:
                    self.active.pop(str(task_id), None)

            runner = asyncio.create_task(resume(), name=f"ultron-resume-{task_id}")
            self.active[str(task_id)] = runner
            await self.events.emit(
                "task.resumed",
                {"approved_execution": execution["id"], "resume_step": continuation["step_index"]},
                str(task_id),
            )
        else:
            self.continuations.delete(str(task_id))
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
        allowed_tools = task.get("allowed_tools")
        contract_allows_tool = allowed_tools is None or call.tool_name in allowed_tools
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
        if not contract_allows_tool:
            reason = "Ferramenta bloqueada pelo contrato da missão."
            self.db.execute(
                "UPDATE tool_executions SET status='blocked', error=?, completed_at=? WHERE id=?",
                (reason, utcnow(), execution_id),
            )
            self._trace(
                task_id,
                "mission_contract.tool_blocked",
                payload={"tool": call.tool_name, "allowed_tools": allowed_tools},
            )
            await self.events.emit(
                "tool.blocked",
                {"execution_id": execution_id, "reason": reason},
                task_id,
            )
            return {"status": "blocked", "execution_id": execution_id, "error": reason}
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
            "metadata": result.metadata,
        }
        await self.events.emit("tool.completed", payload, task["id"])
        return {"status": status, **payload}

    async def _run_loop(self, task_id: str) -> None:
        started = monotonic()
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
            await self._transition(task_id, CognitiveState.UNDERSTAND, {"objective": task["objective"]})
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
            routed_context = self.context_builder.build(task)
            await self.events.emit(
                "experience.routed",
                {
                    "task_signature_id": routed_context.task_signature_id,
                    "family": routed_context.task_signature.family,
                    "candidate_count": routed_context.candidate_count,
                    "injected": routed_context.injected,
                    "routing_decision_ids": routed_context.routing_decision_ids,
                },
                task_id,
            )
            await self._transition(
                task_id,
                CognitiveState.DELIBERATE,
                {
                    "memory_count": len(memories),
                    "experience_candidates": routed_context.candidate_count,
                    "experience_injected": routed_context.injected,
                },
            )
            orientation = self.task_orientations.get(str(task_id))
            if self.settings.controller_mode in {"next_action", "short_horizon"}:
                if orientation is not None:
                    await self._run_receding_horizon(task, memories, routed_context.routed_procedures, orientation=orientation)
                else:
                    await self._run_receding_horizon(task, memories, routed_context.routed_procedures)
                return
            if orientation is not None:
                plan = await self._make_plan(task, memories, routed_context.routed_procedures, orientation=orientation)
            else:
                plan = await self._make_plan(task, memories, routed_context.routed_procedures)
            revision = self._save_plan(task_id, plan)
            await self._transition(
                task_id,
                CognitiveState.PLAN,
                {"steps": len(plan.steps), "confidence": plan.confidence, "revision": revision},
            )
            await self.events.emit("plan.created", plan.model_dump(mode="json"), task_id)
            self._update_task(task_id, status=TaskStatus.RUNNING, confidence=plan.confidence)
            await self._execute_plan(
                task_id,
                task,
                plan,
                revision,
                0,
                [],
                [],
                routed_context,
                started,
                memories,
            )
        except RuntimeError as exc:
            if str(exc) == "TASK_CANCELLED":
                return
            await self._fail(task_id, str(exc))
        except Exception as exc:
            await self._fail(task_id, f"Erro não tratado do orquestrador: {exc}")
        finally:
            self.active.pop(task_id, None)

    async def resolve_external_outcome(self, task_id: str, evaluation: dict[str, Any]) -> OutcomeResult:
        task = self.get_task(task_id)
        if not task:
            raise KeyError("Tarefa não encontrada.")
        if task.get("status") != TaskStatus.WAITING_OUTCOME.value:
            raise ValueError("A tarefa não aguarda outcome externo.")
        outcome = OutcomeAuthority().decide(private_evaluation=evaluation)
        if outcome.success:
            self._update_task(task_id, status=TaskStatus.COMPLETED, completed_at=utcnow(), error=None)
            await self._transition(task_id, CognitiveState.COMPLETE, {"external_outcome": True})
            await self.events.emit("task.completed", {"authority": outcome.authority_level}, task_id)
            return outcome
        false_stops = len([row for row in self.db.all("SELECT event_type FROM execution_traces WHERE task_id=?", (task_id,)) if row["event_type"] == "cognition.false_stop"]) + 1
        self._trace(task_id, "cognition.false_stop", payload={"count": false_stops, "authority": outcome.authority_level})
        if false_stops >= int(self.settings.cognition.get("max_false_stops", 2)):
            await self._fail(task_id, "FALSE_STOP_LIMIT")
            return outcome
        self._update_task(task_id, status=TaskStatus.RUNNING, error=None)
        await self.events.emit("cognition.outcome_rejected", {"evidence_refs": outcome.evidence_refs[:3]}, task_id)
        await self.run(task_id)
        return outcome

    async def _run_receding_horizon(
        self,
        task: dict[str, Any],
        memories: list[dict[str, Any]],
        routed_procedures: list[str],
        *,
        orientation: OrientationSnapshot | None = None,
    ) -> None:
        task_id = str(task["id"])
        await self.events.emit("cognition.iteration.started", {"mode": self.settings.controller_mode}, task_id)
        snapshot = await self.horizon.ensure_initial_observation(task, orientation=orientation)
        outline = await self.horizon.create_outline(task)
        if outline:
            self._trace(task_id, "mission_outline.created", payload=outline.model_dump(mode="json"))
        invalid_decisions = 0
        false_stops = 0
        progress = ProgressTracker()
        max_iterations = min(int(self.settings.cognition.get("max_iterations", 30)), int(self.settings.limits["max_steps"]))
        per_cycle = 3 if self.settings.controller_mode == "short_horizon" else 1
        for _ in range(max_iterations):
            current = self.get_task(task_id)
            if not current:
                return
            if self.horizon.contract.remaining_budget(current) <= 0:
                await self._fail(task_id, "HORIZON_ACTION_BUDGET_EXHAUSTED")
                return
            block_actions = None
            if self.settings.controller_mode == "short_horizon":
                try:
                    block_actions = (await self.horizon.decide_short_horizon(current, snapshot, outline=outline)).actions
                    self._trace(task_id, "cognition.short_horizon_block", payload={"actions": len(block_actions)})
                except Exception as exc:
                    invalid_decisions += 1
                    self._trace(task_id, "cognition.structured_failure", payload={"error": str(exc)[:1000], "count": invalid_decisions})
                    continue
            for _block_index in range(per_cycle):
                current = self.get_task(task_id)
                if not current or self.horizon.contract.remaining_budget(current) <= 0:
                    break
                try:
                    action = (
                        block_actions[_block_index]
                        if block_actions is not None and _block_index < len(block_actions)
                        else await self.horizon.decide_next_action(
                            current,
                            snapshot,
                            outline=outline,
                            routed_procedures=routed_procedures,
                            memory_summaries=[str(item["summary"]) for item in memories],
                        )
                    )
                except Exception as exc:
                    invalid_decisions += 1
                    self._trace(task_id, "cognition.structured_failure", payload={"error": str(exc)[:1000], "count": invalid_decisions})
                    if invalid_decisions >= 3:
                        await self._fail(task_id, "COGNITIVE_ACTION_SELECTION_FAILURE")
                        return
                    continue
                observation, snapshot, validation = await self.horizon.execute_iteration(current, action, snapshot)
                if not validation.accepted:
                    invalid_decisions += 1
                    if invalid_decisions >= 3:
                        await self._fail(task_id, "COGNITIVE_ACTION_SELECTION_FAILURE")
                        return
                    continue
                invalid_decisions = 0
                if action.stop:
                    self._trace(task_id, "cognition.stop_proposed", payload={"reason": action.stop_reason})
                    if current.get("requires_external_outcome"):
                        self._update_task(task_id, status=TaskStatus.WAITING_OUTCOME, error=None)
                        await self.events.emit("cognition.waiting_outcome", {"reason": action.stop_reason}, task_id)
                        return
                    false_stops += 1
                    self._trace(task_id, "cognition.false_stop", payload={"reason": action.stop_reason, "count": false_stops})
                    if false_stops >= 2:
                        await self._fail(task_id, "FALSE_STOP_LIMIT")
                        return
                    continue
                if observation:
                    action_loop, stagnation, progress_signal = progress.assess(
                        tool=action.tool,
                        arguments=action.arguments,
                        observations=snapshot.recent_observations,
                        output=observation.output_summary,
                        verification_passed=observation.verification_passed,
                        subgoal_completed=observation.verification_passed and action.subgoal_id is not None,
                    )
                    self._trace(task_id, "cognition.progress", payload=progress_signal.model_dump(mode="json"))
                    if not observation.ok:
                        self._trace(task_id, "cognition.observation.failed", payload=observation.model_dump(mode="json"))
                    if action_loop:
                        self._trace(task_id, "cognition.action_loop", payload={"tool": action.tool, "iteration": snapshot.iteration})
                        snapshot.failed_strategies.append("ACTION_LOOP")
                    if stagnation:
                        self._trace(task_id, "cognition.stagnation", payload={"iteration": snapshot.iteration})
                        snapshot.failed_strategies.append("STAGNATION")
                        self.horizon.persist_snapshot(snapshot)
            await self.events.emit("cognition.iteration.started", {"iteration": snapshot.iteration + 1}, task_id)
        await self._fail(task_id, "HORIZON_ITERATION_LIMIT")

    async def _execute_plan(
        self,
        task_id: str,
        task: dict[str, Any],
        plan: Plan,
        revision: int,
        start_index: int,
        actions: list[dict[str, Any]],
        errors: list[str],
        routed_context: Any,
        started: float,
        memories: list[dict[str, Any]],
        pending_result: dict[str, Any] | None = None,
    ) -> None:
        """Executa ou retoma um plano, verificando cada etapa antes de avançar."""
        index = start_index
        pending = pending_result
        while index < len(plan.steps):
            self._assert_limits(task_id, started)
            if self._cancelled(task_id):
                return
            step = plan.steps[index]
            await self._transition(
                task_id,
                CognitiveState.POLICY_CHECK,
                {"step": step.id, "action": step.action, "revision": revision, "index": index},
            )
            await self.events.emit("task.step", {"step": step.model_dump(mode="json"), "revision": revision}, task_id)
            result: dict[str, Any] | None = None
            if pending is not None:
                result, pending = pending, None
            elif step.tool:
                await self._transition(task_id, CognitiveState.ACT, {"step": step.id, "tool": step.tool})
                result = await self.execute_tool(task_id, ToolCall(tool_name=step.tool, arguments=step.arguments))
                if result["status"] == "waiting_approval":
                    payload = {
                        "plan": plan.model_dump(mode="json"),
                        "actions": actions,
                        "errors": errors,
                        "routed_context": self._serialize_context(routed_context),
                        "memories": memories,
                    }
                    self.continuations.save(
                        task_id,
                        str(result["approval_id"]),
                        str(result["execution_id"]),
                        revision,
                        index,
                        payload,
                    )
                    await self._transition(
                        task_id,
                        CognitiveState.PAUSED,
                        {"reason": "waiting_approval", "step": step.id, "revision": revision, "index": index},
                    )
                    return
            if result is not None:
                actions.append(result)
                await self._transition(
                    task_id,
                    CognitiveState.OBSERVE_RESULT,
                    {"step": step.id, "ok": result["status"] == "completed"},
                )
            verification = self.verifier.verify(
                step,
                task,
                result,
                prior_steps_verified=not errors,
            )
            await self._transition(
                task_id,
                CognitiveState.VERIFY,
                {
                    "step": step.id,
                    "accepted": verification.accepted,
                    "basis": verification.basis,
                    "condition": verification.condition,
                },
            )
            evidence_payload = [
                {"kind": item.kind, "value": item.value, "source": item.source}
                for item in verification.evidence
            ]
            self._trace(
                task_id,
                "step_verified",
                revision=revision,
                step_id=step.id,
                evidence=evidence_payload,
                router_decision_ids=routed_context.routing_decision_ids,
                payload={"accepted": verification.accepted, "basis": verification.basis, "condition": verification.condition},
            )
            await self.events.emit(
                "step.verified",
                {
                    "step": step.id,
                    "accepted": verification.accepted,
                    "basis": verification.basis,
                    "condition": verification.condition,
                    "evidence": evidence_payload,
                },
                task_id,
            )
            if not verification.accepted:
                error = (
                    str(result.get("error"))
                    if result and result.get("error")
                    else f"Verificação falhou: {step.success_condition}"
                )
                errors.append(error)
                failure = self.recovery.classify(error, step.tool, len(errors))
                recovery = self.recovery.propose(failure, self.settings.limits["max_replans"])
                self.recovery.persist(self.db, task_id, failure, recovery)
                await self.events.emit(
                    "failure.classified",
                    {
                        "category": failure.category.value,
                        "recoverable": failure.recoverable,
                        "strategy": recovery.strategy,
                    },
                    task_id,
                )
                replacement = await self._replan(
                    task_id,
                    task,
                    plan,
                    step,
                    errors,
                    memories,
                    routed_context.routed_procedures,
                ) if recovery.retry else None
                if replacement is None:
                    await self._finalize_execution(task_id, task, actions, errors, routed_context, started)
                    return
                plan, revision = replacement
                # A falha permanece auditável em `failures`, mas foi superada por uma revisão.
                errors.clear()
                index = 0
                continue
            self.db.execute(
                "UPDATE tasks SET step_count=step_count+1, updated_at=? WHERE id=?",
                (utcnow(), task_id),
            )
            index += 1
        await self._finalize_execution(task_id, task, actions, errors, routed_context, started)

    async def _finalize_execution(
        self,
        task_id: str,
        task: dict[str, Any],
        actions: list[dict[str, Any]],
        errors: list[str],
        routed_context: Any,
        started: float,
    ) -> None:
        success = not errors
        self.continuations.delete(task_id)
        lessons = [
            "O plano foi concluído com verificações determinísticas por etapa."
            if success
            else f"A execução encontrou: {errors[-1]}"
        ]
        await self._transition(task_id, CognitiveState.LEARN, {"success": success})
        if task.get("requires_external_outcome"):
            experience = {
                "stored": False,
                "verification_state": "pending",
                "reason": "external_outcome_required",
            }
            await self.events.emit(
                "memory.pending_external_outcome",
                {"internal_success": success, "experience": experience},
                task_id,
            )
        else:
            experience_id = self.memory.store_experience(
                task_id,
                "structured-plan",
                actions,
                "Tarefa concluída" if success else "Tarefa falhou",
                success,
                errors,
                lessons,
                0.85 if success else 0.3,
            )
            self.context_builder.record_outcome(
                task_id,
                routed_context,
                success=success,
                experience_id=experience_id,
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
            self._update_task(task_id, status=TaskStatus.COMPLETED, completed_at=utcnow(), error=None)
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

    async def _make_plan(
        self,
        task: dict[str, Any],
        memories: list[dict[str, Any]],
        routed_procedures: list[str] | None = None,
        *,
        orientation: OrientationSnapshot | None = None,
    ) -> Plan:
        allowed_tools = task.get("allowed_tools")
        planner_tools = allowed_tools if allowed_tools is not None else [m["name"] for m in self.tools.list_manifests()]
        action_budget = task.get("action_budget")
        contract_text = (
            f"Contrato da missão — ferramentas autorizadas: {planner_tools}; orçamento de ações: {action_budget}. "
            "Não proponha ferramenta fora da lista autorizada e não ultrapasse o teto do orçamento."
            if action_budget is not None
            else f"Ferramentas disponíveis: {planner_tools}."
        )
        obs_text = "\n".join(orientation.observations) if (orientation and orientation.observations) else "nenhuma"
        prompt = [
            {
                "role": "system",
                "content": "Você é o planejador do UltronPro. Retorne estritamente JSON: objective, steps[{id,action,tool,arguments,success_condition,risk}], risks, confidence. Use somente ferramentas fornecidas quando indispensáveis. Cada success_condition DEVE usar uma forma determinística: tool_exit_zero, file_exists:<caminho>, file_contains:<caminho>::<texto>, prior_steps_completed ou task_context.",
            },
            {
                "role": "user",
                "content": (
                    f"Objetivo: {task['objective']}\nWorkspace: {task['workspace']}\n"
                    f"Observação inicial do ambiente:\n{obs_text}\n"
                    f"Memórias relevantes: {[m['summary'] for m in memories]}\n"
                    f"Experiências procedurais roteadas: {routed_procedures or []}\n"
                    f"{contract_text}"
                ),
            },
        ]
        async def record_response(response: Any, is_repair: bool) -> None:
            self.db.execute(
                "INSERT INTO model_calls (id,task_id,provider,model,purpose,latency_ms,prompt_tokens,output_tokens,finish_reason,seed,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    task["id"],
                    "local",
                    response.model,
                    "planning_repair" if is_repair else "planning",
                    response.latency_ms,
                    response.usage.prompt_tokens,
                    response.usage.output_tokens,
                    response.finish_reason,
                    self.planning_seed,
                    utcnow(),
                ),
            )
            self.db.execute(
                "UPDATE tasks SET llm_call_count=llm_call_count+1 WHERE id=?", (task["id"],)
            )

        try:
            plan = await self.models.structured(
                Plan,
                prompt,
                model_name=self.models.primary_name,
                seed=self.planning_seed,
                on_response=record_response,
            )
            self.plan_sources[str(task["id"])] = "model_structured"
            return plan
        except Exception:
            self.plan_sources[str(task["id"])] = "fallback_after_model_error"
            return self._fallback_plan(task)

    def _fallback_plan(self, task: dict[str, Any]) -> Plan:
        objective = task["objective"].lower()
        steps = [
            PlanStep(
                id=1,
                action="Analisar objetivo e limites do workspace",
                success_condition="task_context",
            )
        ]
        if any(token in objective for token in ("arquivo", "document", "relatório", "relatorio")):
            if self.tools.get_manifest("file.write"):
                steps.append(
                    PlanStep(
                        id=2,
                        action="Criar registro inicial no workspace",
                        tool="file.write",
                        arguments={
                            "path": "ultron_task_note.md",
                            "content": f"# {task['title']}\n\n{task['objective']}\n",
                        },
                        success_condition=f"file_contains:ultron_task_note.md::{task['title']}",
                        risk=RiskLevel.R2,
                    )
                )
            elif self.tools.get_manifest("python.execute"):
                content = repr(f"# {task['title']}\n\n{task['objective']}\n")
                steps.append(
                    PlanStep(
                        id=2,
                        action="Criar registro inicial via execução isolada",
                        tool="python.execute",
                        arguments={
                            "code": f"from pathlib import Path; Path('ultron_task_note.md').write_text({content}, encoding='utf-8')",
                        },
                        success_condition=f"file_contains:ultron_task_note.md::{task['title']}",
                        risk=RiskLevel.R1,
                    )
                )
        steps.append(
            PlanStep(
                id=len(steps) + 1,
                action="Verificar conclusão operacional",
                success_condition="prior_steps_completed",
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
        memories: list[dict[str, Any]],
        routed_procedures: list[str],
    ) -> tuple[Plan, int] | None:
        row = self.get_task(task_id) or task
        if int(row["replan_count"]) >= self.settings.limits["max_replans"]:
            return None
        next_attempt = int(row["replan_count"]) + 1
        self.db.execute(
            "UPDATE tasks SET replan_count=replan_count+1, updated_at=? WHERE id=?",
            (utcnow(), task_id),
        )
        failure_context = (
            f"Falha verificável na etapa {failed_step.id} ({failed_step.action}): {errors[-1]}. "
            "Crie uma revisão com uma alternativa segura, preservando as etapas já verificadas."
        )
        await self._transition(
            task_id, CognitiveState.REFLECT, {"failed_step": failed_step.id, "error": errors[-1]}
        )
        await self.events.emit(
            "task.reflect",
            {"failed_step": failed_step.id, "lesson": failure_context},
            task_id,
        )
        await self._transition(task_id, CognitiveState.REPLAN, {"revision": next_attempt + 1})
        replan_memories = [*memories, {"summary": failure_context}]
        revised = await self._make_plan(task, replan_memories, routed_procedures)
        revision = self._save_plan(task_id, revised)
        await self._transition(
            task_id,
            CognitiveState.PLAN,
            {"revision": revision, "replanned_from": failed_step.id, "steps": len(revised.steps)},
        )
        await self.events.emit(
            "plan.revised",
            {
                "revision": revision,
                "failed_step": failed_step.id,
                "strategy": "revisão gerada a partir de evidência determinística de falha",
            },
            task_id,
        )
        return revised, revision

    def _save_plan(self, task_id: str, plan: Plan) -> int:

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
        return revision

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
        action_budget = task.get("action_budget")
        mission_tool_limit = int(action_budget[1]) if action_budget is not None else self.settings.limits["max_tool_calls"]
        tool_limit = min(self.settings.limits["max_tool_calls"], mission_tool_limit)
        if int(task["tool_call_count"]) >= tool_limit:
            raise RuntimeError("Limite de chamadas de ferramenta excedido pelo contrato da missão.")
        if int(task["llm_call_count"]) >= self.settings.limits["max_llm_calls"]:
            raise RuntimeError("Limite de chamadas ao modelo excedido.")

    def _cancelled(self, task_id: str) -> bool:
        return self.cancel_events.get(task_id, asyncio.Event()).is_set()
