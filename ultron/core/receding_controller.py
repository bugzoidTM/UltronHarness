"""Controle cognitivo de horizonte recuado sobre o mesmo stack de segurança do orquestrador."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.models.gateway import ModelGateway
from ultron.schemas import (
    ActionObservation,
    CognitiveStateSnapshot,
    MissionOutline,
    NextAction,
    OrientationSnapshot,
    PlanStep,
    ShortHorizonDecision,
    ToolCall,
    VerificationSpec,
)
from ultron.tools.registry import ToolRegistry


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


ToolExecutor = Callable[[str, ToolCall], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ContractValidation:
    accepted: bool
    reason: str = ""


class MissionContractValidator:
    """Valida uma ação proposta antes da Política de Segurança existente."""

    def __init__(self, tools: ToolRegistry, settings: Settings):
        self.tools, self.settings = tools, settings

    def validate(self, task: dict[str, Any], action: NextAction) -> ContractValidation:
        if action.stop:
            return ContractValidation(True)
        if not action.tool:
            return ContractValidation(False, "next_action_sem_tool")
        allowed = task.get("allowed_tools")
        if allowed is not None and action.tool not in allowed:
            return ContractValidation(False, "tool_outside_mission_contract")
        if not self.tools.get_manifest(action.tool):
            return ContractValidation(False, "tool_not_registered")
        if not isinstance(action.arguments, dict):
            return ContractValidation(False, "arguments_not_object")
        maximum = self._effective_maximum(task)
        if int(task.get("tool_call_count") or 0) >= maximum:
            return ContractValidation(False, "mission_action_budget_exhausted")
        return ContractValidation(True)

    def remaining_budget(self, task: dict[str, Any]) -> int:
        return max(0, self._effective_maximum(task) - int(task.get("tool_call_count") or 0))

    def _effective_maximum(self, task: dict[str, Any]) -> int:
        budget = task.get("action_budget")
        mission_maximum = int(budget[1]) if budget is not None else int(self.settings.limits["max_tool_calls"])
        return min(int(self.settings.limits["max_tool_calls"]), mission_maximum)


class RecedingHorizonController:
    """Decide uma ação, observa, verifica e persiste antes de decidir novamente."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        events: EventBus,
        models: ModelGateway,
        tools: ToolRegistry,
        verifier: StepSuccessVerifier,
        execute_tool: ToolExecutor,
        *,
        planning_seed: int | None = None,
    ):
        self.settings, self.db, self.events = settings, db, events
        self.models, self.tools, self.verifier, self.execute_tool = models, tools, verifier, execute_tool
        self.planning_seed = planning_seed
        self.contract = MissionContractValidator(tools, settings)

    def latest_snapshot(self, task: dict[str, Any]) -> CognitiveStateSnapshot:
        row = self.db.one(
            "SELECT * FROM cognitive_snapshots WHERE task_id=? ORDER BY iteration DESC LIMIT 1",
            (task["id"],),
        )
        if not row:
            return CognitiveStateSnapshot(
                task_id=str(task["id"]),
                objective=str(task["objective"]),
                tool_calls_used=int(task.get("tool_call_count") or 0),
                remaining_action_budget=self.contract.remaining_budget(task),
                replan_count=int(task.get("replan_count") or 0),
            )
        return CognitiveStateSnapshot(
            task_id=str(task["id"]),
            objective=str(task["objective"]),
            current_subgoal_id=row["current_subgoal_id"],
            completed_subgoals=self.db.parse_json(row["completed_subgoals_json"], []),
            known_facts=self.db.parse_json(row["known_facts_json"], []),
            open_questions=self.db.parse_json(row["open_questions_json"], []),
            recent_observations=self.db.parse_json(row["recent_observations_json"], []),
            failed_strategies=self.db.parse_json(row["failed_strategies_json"], []),
            external_feedback=self.db.parse_json(row["external_feedback_json"], []),
            evidence_refs=self.db.parse_json(row["evidence_refs_json"], []),
            tool_calls_used=int(row["tool_calls_used"]),
            remaining_action_budget=int(row["remaining_action_budget"]),
            replan_count=int(task.get("replan_count") or 0),
            iteration=int(row["iteration"]),
        )

    def persist_snapshot(self, snapshot: CognitiveStateSnapshot) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO cognitive_snapshots
               (id,task_id,iteration,current_subgoal_id,completed_subgoals_json,known_facts_json,open_questions_json,recent_observations_json,failed_strategies_json,external_feedback_json,evidence_refs_json,tool_calls_used,remaining_action_budget,created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                snapshot.task_id,
                snapshot.iteration,
                snapshot.current_subgoal_id,
                self.db.json(snapshot.completed_subgoals),
                self.db.json(snapshot.known_facts),
                self.db.json(snapshot.open_questions),
                self.db.json(snapshot.recent_observations),
                self.db.json(snapshot.failed_strategies),
                self.db.json(snapshot.external_feedback),
                self.db.json(snapshot.evidence_refs),
                snapshot.tool_calls_used,
                snapshot.remaining_action_budget,
                utcnow(),
            ),
        )

    async def ensure_initial_observation(
        self,
        task: dict[str, Any],
        *,
        orientation: OrientationSnapshot | None = None,
    ) -> CognitiveStateSnapshot:
        snapshot = self.latest_snapshot(task)
        if snapshot.iteration or "initial_environment_observation" in snapshot.evidence_refs or "frozen_orientation_snapshot" in snapshot.evidence_refs:
            return snapshot

        if orientation is not None:
            obs_list = list(orientation.observations)
            evidence_refs = list(orientation.evidence_refs) if orientation.evidence_refs else ["frozen_orientation_snapshot"]
            updated = CognitiveStateSnapshot(
                task_id=str(task["id"]),
                objective=str(task["objective"]),
                current_subgoal_id=snapshot.current_subgoal_id,
                completed_subgoals=list(snapshot.completed_subgoals),
                known_facts=obs_list[-self._limit("max_known_facts") :] if obs_list else [],
                open_questions=list(snapshot.open_questions),
                recent_observations=obs_list[-self._limit("recent_observations") :] if obs_list else [],
                failed_strategies=list(snapshot.failed_strategies),
                evidence_refs=evidence_refs,
                tool_calls_used=int(task.get("tool_call_count") or 0),
                remaining_action_budget=self.contract.remaining_budget(task),
                replan_count=int(task.get("replan_count") or 0),
                iteration=0,
            )
            self.persist_snapshot(updated)
            if obs_list:
                await self.events.emit(
                    "cognition.observation.received",
                    {
                        "tool": "orientation",
                        "ok": True,
                        "output_summary": obs_list[0],
                        "verification_passed": True,
                        "evidence_refs": evidence_refs,
                    },
                    str(task["id"]),
                )
            await self.events.emit("cognition.state.updated", {"iteration": updated.iteration}, str(task["id"]))
            return updated

        allowed = task.get("allowed_tools")
        if allowed is not None and "file.list" not in allowed:
            self.persist_snapshot(snapshot)
            return snapshot
        result = await self.execute_tool(str(task["id"]), ToolCall(tool_name="file.list", arguments={"path": "."}))
        observation = self._observation("file.list", result, verification_passed=result.get("status") == "completed")
        updated = self._updated_snapshot(task, snapshot, observation, evidence_ref="initial_environment_observation")
        self.persist_snapshot(updated)
        await self.events.emit("cognition.observation.received", observation.model_dump(mode="json"), str(task["id"]))
        await self.events.emit("cognition.state.updated", {"iteration": updated.iteration}, str(task["id"]))
        return updated

    async def create_outline(
        self,
        task: dict[str, Any],
        *,
        snapshot: CognitiveStateSnapshot | None = None,
        orientation: OrientationSnapshot | None = None,
    ) -> MissionOutline | None:
        obs_text = "nenhuma"
        if orientation and orientation.observations:
            obs_text = "\n".join(orientation.observations)
        elif snapshot and snapshot.recent_observations:
            obs_text = "\n".join(snapshot.recent_observations)
        prompt = [
            {"role": "system", "content": "Crie apenas subobjetivos amplos. Não invente caminhos, argumentos ou resultados futuros. Responda no schema MissionOutline."},
            {"role": "user", "content": f"Objetivo: {task['objective']}\nObservação inicial do ambiente:\n{obs_text}\nFerramentas autorizadas: {task.get('allowed_tools')}"},
        ]
        try:
            return await self.models.structured(
                MissionOutline,
                prompt,
                model_name=self.models.primary_name,
                seed=self.planning_seed,
                repair_attempts=int(self.settings.cognition.get("structured_repair_attempts", 2)),
                on_response=lambda response, repaired: self._record_model_response(task, response, repaired, "horizon_outline"),
            )
        except Exception:
            return None

    async def decide_next_action(
        self,
        task: dict[str, Any],
        snapshot: CognitiveStateSnapshot,
        *,
        outline: MissionOutline | None = None,
        routed_procedures: list[str] | None = None,
        memory_summaries: list[str] | None = None,
    ) -> NextAction:
        if self._has_unobserved_action(str(task["id"])):
            raise RuntimeError("OBSERVATION_REQUIRED_BEFORE_NEXT_DECISION")
        current_subgoal = self._subgoal(outline, snapshot.current_subgoal_id)
        obs_text = "\n".join(snapshot.recent_observations) if snapshot.recent_observations else "nenhuma"
        prompt = [
            {
                "role": "system",
                "content": "Você controla uma missão local passo a passo. Escolha somente a próxima ação necessária com base nas evidências atuais. Não invente arquivos ou resultados não observados. Use somente ferramentas permitidas. Respeite o orçamento restante. Se o objetivo já estiver demonstravelmente concluído, proponha stop=true. Responda somente no schema NextAction.",
            },
            {
                "role": "user",
                "content": (
                    f"Objetivo: {task['objective']}\nSubobjetivo atual: {current_subgoal}\n"
                    f"Observação inicial do ambiente:\n{obs_text}\n"
                    f"Outline: {[item.description for item in outline.subgoals] if outline else []}\n"
                    f"Ferramentas autorizadas: {task.get('allowed_tools')}\nOrçamento restante: {snapshot.remaining_action_budget}\n"
                    f"Fatos conhecidos: {snapshot.known_facts[-self._limit('max_known_facts') :]}\n"
                    f"Observações recentes: {snapshot.recent_observations[-self._limit('recent_observations') :]}\n"
                    f"Estratégias falhas: {snapshot.failed_strategies[-self._limit('max_failed_strategies') :]}\n"
                    f"Feedback externo sanitizado: {snapshot.external_feedback[-3:]}\n"
                    f"Procedimentos roteados: {routed_procedures or []}\nMemórias: {memory_summaries or []}"
                ),
            },
        ]
        action = await self.models.structured(
            NextAction,
            prompt,
            model_name=self.models.primary_name,
            seed=self.planning_seed,
            repair_attempts=int(self.settings.cognition.get("structured_repair_attempts", 2)),
            on_response=lambda response, repaired: self._record_model_response(task, response, repaired, "horizon_next_action"),
            on_decision=lambda initial, final, repairs, error, category: self._record_decision(task, "next_action", snapshot.iteration + 1, initial, final, repairs, error, category),
        )
        await self.events.emit("cognition.next_action.proposed", action.model_dump(mode="json"), str(task["id"]))
        return action

    async def decide_short_horizon(
        self, task: dict[str, Any], snapshot: CognitiveStateSnapshot, *, outline: MissionOutline | None = None
    ) -> ShortHorizonDecision:
        if self._has_unobserved_action(str(task["id"])):
            raise RuntimeError("OBSERVATION_REQUIRED_BEFORE_NEXT_DECISION")
        obs_text = "\n".join(snapshot.recent_observations) if snapshot.recent_observations else "nenhuma"
        prompt = [
            {"role": "system", "content": "Escolha um bloco de uma a três ações locais. Cada ação deve ser executável com as ferramentas autorizadas. O bloco será invalidado se a observação tornar as próximas ações inadequadas. Responda somente no schema ShortHorizonDecision."},
            {"role": "user", "content": f"Objetivo: {task['objective']}\nObservação inicial do ambiente:\n{obs_text}\nFerramentas: {task.get('allowed_tools')}\nOrçamento: {snapshot.remaining_action_budget}\nObservações: {snapshot.recent_observations[-self._limit('recent_observations') :]}\nFeedback externo sanitizado: {snapshot.external_feedback[-3:]}\nOutline: {[item.description for item in outline.subgoals] if outline else []}"},
        ]
        return await self.models.structured(
            ShortHorizonDecision,
            prompt,
            model_name=self.models.primary_name,
            seed=self.planning_seed,
            repair_attempts=int(self.settings.cognition.get("structured_repair_attempts", 2)),
            on_response=lambda response, repaired: self._record_model_response(task, response, repaired, "horizon_short_block"),
            on_decision=lambda initial, final, repairs, error, category: self._record_decision(task, "short_horizon", snapshot.iteration + 1, initial, final, repairs, error, category),
        )

    async def execute_iteration(
        self,
        task: dict[str, Any],
        action: NextAction,
        snapshot: CognitiveStateSnapshot,
    ) -> tuple[ActionObservation | None, CognitiveStateSnapshot, ContractValidation]:
        validation = self.contract.validate(task, action)
        if not validation.accepted:
            await self.events.emit(
                "cognition.next_action.rejected",
                {"reason": validation.reason, "action": action.model_dump(mode="json")},
                str(task["id"]),
            )
            return None, snapshot, validation
        if action.stop:
            await self.events.emit("cognition.stop.proposed", action.model_dump(mode="json"), str(task["id"]))
            return None, snapshot, validation
        action_id = str(uuid4())
        self._persist_action(action_id, task, snapshot, action, "proposed")
        result = await self.execute_tool(str(task["id"]), ToolCall(tool_name=str(action.tool), arguments=action.arguments))
        self.db.execute(
            "UPDATE cognitive_actions SET status=?, executed_at=? WHERE action_id=?",
            (str(result.get("status", "unknown")), utcnow(), action_id),
        )
        verification = self.verifier.verify(
            PlanStep(
                id=1,
                action=action.intent,
                tool=action.tool,
                arguments=action.arguments,
                success_condition=self._legacy_condition(action.expected_evidence),
            ),
            task,
            result,
            prior_steps_verified=True,
        )
        observation = self._observation(str(action.tool), result, verification.accepted)
        evidence_ref = f"cognitive_action:{action_id}"
        updated = self._updated_snapshot(task, snapshot, observation, evidence_ref=evidence_ref, subgoal_id=action.subgoal_id)
        self.persist_snapshot(updated)
        await self.events.emit("cognition.observation.received", observation.model_dump(mode="json"), str(task["id"]))
        await self.events.emit("cognition.state.updated", {"iteration": updated.iteration, "action_id": action_id}, str(task["id"]))
        if verification.accepted and action.subgoal_id is not None:
            await self.events.emit("cognition.subgoal.completed", {"subgoal_id": action.subgoal_id}, str(task["id"]))
        return observation, updated, validation

    async def _record_decision(self, task: dict[str, Any], kind: str, iteration: int, initial: bool, final: bool, repairs: int, error: str | None, error_category: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO structured_decisions (id,task_id,controller_mode,decision_kind,iteration,initial_valid,final_valid,repair_attempts,validation_error_class,error_category,model,seed,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), task["id"], self.settings.controller_mode, kind, iteration, int(initial), int(final), repairs, error, error_category, self.models.primary_name, self.planning_seed, utcnow()),
        )

    async def _record_model_response(self, task: dict[str, Any], response: Any, repaired: bool, purpose: str) -> None:
        self.db.execute(
            "INSERT INTO model_calls (id,task_id,provider,model,purpose,latency_ms,prompt_tokens,output_tokens,finish_reason,seed,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                task["id"],
                "local",
                response.model,
                f"{purpose}_repair" if repaired else purpose,
                response.latency_ms,
                response.usage.prompt_tokens,
                response.usage.output_tokens,
                response.finish_reason,
                self.planning_seed,
                utcnow(),
            ),
        )
        self.db.execute("UPDATE tasks SET llm_call_count=llm_call_count+1 WHERE id=?", (task["id"],))

    def persist_external_feedback(self, task: dict[str, Any], feedback_identity: str, feedback: str) -> CognitiveStateSnapshot:
        """Anexa somente feedback público ao snapshot antes de uma nova decisão closed-loop."""
        previous = self.latest_snapshot(task)
        updated = CognitiveStateSnapshot(
            task_id=str(task["id"]),
            objective=str(task["objective"]),
            current_subgoal_id=previous.current_subgoal_id,
            completed_subgoals=list(previous.completed_subgoals),
            known_facts=list(previous.known_facts),
            open_questions=list(previous.open_questions),
            recent_observations=list(previous.recent_observations),
            failed_strategies=[*previous.failed_strategies, "EXTERNAL_OUTCOME_REJECTED"][-self._limit("max_failed_strategies") :],
            external_feedback=[*previous.external_feedback, f"{feedback_identity}: {feedback}"][-3:],
            evidence_refs=[*previous.evidence_refs, feedback_identity][-20:],
            tool_calls_used=int(task.get("tool_call_count") or 0),
            remaining_action_budget=self.contract.remaining_budget(task),
            replan_count=int(task.get("replan_count") or 0),
            iteration=previous.iteration + 1,
        )
        self.persist_snapshot(updated)
        return updated

    def _persist_action(
        self,
        action_id: str,
        task: dict[str, Any],
        snapshot: CognitiveStateSnapshot,
        action: NextAction,
        status: str,
    ) -> None:
        self.db.execute(
            """INSERT INTO cognitive_actions
               (id,action_id,task_id,iteration,subgoal_id,tool,arguments_json,expected_evidence_json,status,model,seed,created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                action_id,
                task["id"],
                snapshot.iteration + 1,
                action.subgoal_id,
                action.tool,
                self.db.json(action.arguments),
                self.db.json(action.expected_evidence.model_dump(mode="json")),
                status,
                self.models.primary_name,
                self.planning_seed,
                utcnow(),
            ),
        )

    def _updated_snapshot(
        self,
        task: dict[str, Any],
        previous: CognitiveStateSnapshot,
        observation: ActionObservation,
        *,
        evidence_ref: str,
        subgoal_id: int | None = None,
    ) -> CognitiveStateSnapshot:
        facts = [*previous.known_facts, observation.output_summary] if observation.ok else previous.known_facts
        failures = [*previous.failed_strategies, observation.error or observation.tool] if not observation.ok else previous.failed_strategies
        completed = list(previous.completed_subgoals)
        if observation.verification_passed and subgoal_id is not None and subgoal_id not in completed:
            completed.append(subgoal_id)
        return CognitiveStateSnapshot(
            task_id=str(task["id"]),
            objective=str(task["objective"]),
            current_subgoal_id=subgoal_id or previous.current_subgoal_id,
            completed_subgoals=completed,
            known_facts=facts[-self._limit("max_known_facts") :],
            open_questions=previous.open_questions[-self._limit("max_open_questions") :],
            recent_observations=[*previous.recent_observations, observation.output_summary][-self._limit("recent_observations") :],
            failed_strategies=failures[-self._limit("max_failed_strategies") :],
            external_feedback=previous.external_feedback[-3:],
            evidence_refs=[*previous.evidence_refs, evidence_ref][-20:],
            tool_calls_used=int(task.get("tool_call_count") or 0) + 1,
            remaining_action_budget=max(0, self.contract.remaining_budget(task) - 1),
            replan_count=int(task.get("replan_count") or 0),
            iteration=previous.iteration + 1,
        )

    def _has_unobserved_action(self, task_id: str) -> bool:
        row = self.db.one(
            "SELECT action_id FROM cognitive_actions WHERE task_id=? AND status='proposed' ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        return row is not None

    @staticmethod
    def _observation(tool: str, result: dict[str, Any], verification_passed: bool) -> ActionObservation:
        output = str(result.get("output") or "")[:2000]
        error = str(result["error"])[:2000] if result.get("error") else None
        return ActionObservation(
            tool=tool,
            ok=result.get("status") == "completed",
            output_summary=output,
            error=error,
            verification_passed=verification_passed,
            evidence_refs=[str(result.get("execution_id"))] if result.get("execution_id") else [],
        )

    @staticmethod
    def _legacy_condition(spec: VerificationSpec) -> str:
        if spec.type == "tool_success":
            return "tool_exit_zero"
        if spec.type == "file_exists" and spec.path:
            return f"file_exists:{spec.path}"
        if spec.type == "file_contains" and spec.path and spec.expected is not None:
            return f"file_contains:{spec.path}::{spec.expected}"
        if spec.type == "json_schema" and spec.path and spec.expected:
            return f"json_schema:{spec.path}::{spec.expected}"
        if spec.type == "registered_command" and spec.registry_id:
            return f"registered_command:{spec.registry_id}"
        if spec.type == "prior_step":
            return "prior_steps_completed"
        return "task_context" if spec.type == "task_context" else "tool_exit_zero"

    @staticmethod
    def _subgoal(outline: MissionOutline | None, subgoal_id: int | None) -> str:
        if not outline:
            return ""
        for subgoal in outline.subgoals:
            if subgoal.id == subgoal_id:
                return subgoal.description
        return outline.subgoals[0].description if outline.subgoals else ""

    def _limit(self, name: str) -> int:
        return int(self.settings.cognition.get(name, 10))
