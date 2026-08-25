"""Contratos públicos e internos, com validação rigorosa para o plano de controle."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_OUTCOME = "waiting_outcome"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CognitiveState(str, Enum):
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    UNDERSTAND = "UNDERSTAND"
    RETRIEVE_MEMORY = "RETRIEVE_MEMORY"
    DELIBERATE = "DELIBERATE"
    PLAN = "PLAN"
    POLICY_CHECK = "POLICY_CHECK"
    ACT = "ACT"
    OBSERVE_RESULT = "OBSERVE_RESULT"
    VERIFY = "VERIFY"
    REFLECT = "REFLECT"
    REPLAN = "REPLAN"
    LEARN = "LEARN"
    COMPLETE = "COMPLETE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class GoalCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    priority: float = Field(default=0.5, ge=0, le=1)
    success_metric: str | None = Field(default=None, max_length=200)


class GoalRead(GoalCreate):
    id: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=3, max_length=10000)
    goal_id: str | None = None
    priority: float = Field(default=0.5, ge=0, le=1)
    workspace: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]+$")
    autonomy_mode: int = Field(default=2, ge=0, le=4)
    allowed_tools: list[str] | None = Field(default=None, max_length=50)
    action_budget: tuple[int, int] | None = None
    requires_external_outcome: bool = False

    @field_validator("allowed_tools")
    @classmethod
    def validate_allowed_tools(cls, tools: list[str] | None) -> list[str] | None:
        if tools is None:
            return None
        if any(not name or len(name) > 120 for name in tools):
            raise ValueError("Ferramentas autorizadas devem ter nomes não vazios de até 120 caracteres.")
        if len(set(tools)) != len(tools):
            raise ValueError("Ferramentas autorizadas não podem conter duplicatas.")
        return tools

    @field_validator("action_budget")
    @classmethod
    def validate_action_budget(cls, budget: tuple[int, int] | None) -> tuple[int, int] | None:
        if budget is None:
            return None
        minimum, maximum = budget
        if minimum < 0 or maximum < 1 or minimum > maximum:
            raise ValueError("action_budget deve obedecer 0 <= mínimo <= máximo e máximo >= 1.")
        return budget


class TaskRead(TaskCreate):
    id: str
    status: TaskStatus
    step_count: int
    replan_count: int
    tool_call_count: int
    llm_call_count: int
    confidence: float | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cognitive_state: CognitiveState | None = None


class PlanStep(BaseModel):
    id: int = Field(ge=1)
    action: str = Field(min_length=2, max_length=120)
    tool: str | None = Field(default=None, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    success_condition: str = Field(min_length=2, max_length=1000)
    risk: RiskLevel = RiskLevel.R0


class Plan(BaseModel):
    objective: str
    steps: list[PlanStep] = Field(min_length=1, max_length=30)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class MissionSubgoal(BaseModel):
    id: int = Field(ge=1)
    description: str = Field(min_length=3, max_length=500)
    success_hint: str | None = Field(default=None, max_length=500)


class MissionOutline(BaseModel):
    objective: str = Field(min_length=3, max_length=10000)
    subgoals: list[MissionSubgoal] = Field(min_length=1, max_length=10)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class VerificationSpec(BaseModel):
    type: Literal[
        "tool_success",
        "file_exists",
        "file_contains",
        "json_schema",
        "registered_command",
        "prior_step",
        "task_context",
        "none",
    ]
    path: str | None = Field(default=None, max_length=1000)
    expected: str | None = Field(default=None, max_length=4000)
    registry_id: str | None = Field(default=None, max_length=200)


class PredictionClassification(str, Enum):
    CONFIRM = "confirm"
    WEAKEN = "weaken"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


class Prediction(BaseModel):
    version: int = Field(default=1, ge=1)
    prediction_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    action_id: str = Field(min_length=1, max_length=128)
    iteration: int = Field(ge=0)
    hypothesis: str = Field(min_length=1, max_length=2000)
    expected_observation: str = Field(min_length=1, max_length=2000)
    confidence_before: float = Field(ge=0.0, le=1.0)
    action: str = Field(min_length=1, max_length=2000)
    observed: str | None = Field(default=None, max_length=2000)
    confidence_after: float | None = Field(default=None, ge=0.0, le=1.0)
    classification: PredictionClassification | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    predicted_at: str = Field(min_length=1, max_length=80)
    observed_at: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def observation_requires_outcome(self) -> Prediction:
        observed_fields = (self.observed, self.confidence_after, self.classification, self.observed_at)
        if any(value is not None for value in observed_fields) and not all(value is not None for value in observed_fields):
            raise ValueError("Uma previsão observada deve conter todos os campos expected/observed do outcome.")
        return self


class PredictionObservation(BaseModel):
    prediction_id: str = Field(min_length=1, max_length=128)
    action_id: str = Field(min_length=1, max_length=128)
    observed_output: str = Field(max_length=2000)
    result_status: str = Field(min_length=1, max_length=80)
    verification_passed: bool
    confidence_after: float = Field(ge=0.0, le=1.0)
    classification: PredictionClassification
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    observed_at: str = Field(min_length=1, max_length=80)


class EpistemicKind(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class EpistemicClaim(BaseModel):
    kind: EpistemicKind
    content: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    source: str = Field(default="explicit_update", min_length=1, max_length=120)


class EpistemicState(BaseModel):
    version: int = Field(default=1, ge=1)
    known_facts: list[EpistemicClaim] = Field(default_factory=list, max_length=20)
    unknowns: list[EpistemicClaim] = Field(default_factory=list, max_length=20)
    assumptions: list[EpistemicClaim] = Field(default_factory=list, max_length=20)
    hypotheses: list[EpistemicClaim] = Field(default_factory=list, max_length=10)
    hypothesis_confidences: dict[str, float] = Field(default_factory=dict)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    causal_relations: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    derived_facts: list[EpistemicClaim] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(default_factory=list, max_length=20)
    failed_hypotheses: list[str] = Field(default_factory=list, max_length=20)
    active_strategy: str | None = Field(default=None, max_length=1000)
    candidate_strategies: list[str] = Field(default_factory=list, max_length=10)
    evidence_for: dict[str, list[str]] = Field(default_factory=dict)
    evidence_against: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def claim_kinds_are_partitioned(self) -> EpistemicState:
        expected_kinds = {
            "known_facts": EpistemicKind.FACT,
            "unknowns": EpistemicKind.UNKNOWN,
            "assumptions": EpistemicKind.ASSUMPTION,
            "hypotheses": EpistemicKind.HYPOTHESIS,
            "derived_facts": EpistemicKind.INFERENCE,
        }
        for field_name, expected_kind in expected_kinds.items():
            if any(claim.kind != expected_kind for claim in getattr(self, field_name)):
                raise ValueError(f"{field_name} aceita somente claims do tipo {expected_kind.value}.")
        return self

    @model_validator(mode="after")
    def hypothesis_is_not_fact(self) -> EpistemicState:
        fact_contents = {claim.content for claim in self.known_facts}
        hypothesis_contents = {claim.content for claim in self.hypotheses}
        if fact_contents.intersection(hypothesis_contents):
            raise ValueError("Uma hipótese não pode ser promovida silenciosamente a fato.")
        for content, confidence in self.hypothesis_confidences.items():
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"Confiança de hipótese inválida: {content}")
        return self


class NextAction(BaseModel):
    subgoal_id: int | None = Field(default=None, ge=1)
    intent: str = Field(min_length=3, max_length=500)
    tool: str | None = Field(default=None, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_evidence: VerificationSpec
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    stop: bool = False
    stop_reason: str | None = Field(default=None, max_length=500)

    @field_validator("stop_reason")
    @classmethod
    def stop_reason_requires_stop(cls, reason: str | None, info: Any) -> str | None:
        if reason and not info.data.get("stop"):
            raise ValueError("stop_reason exige stop=true.")
        return reason


class ShortHorizonDecision(BaseModel):
    actions: list[NextAction] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def stop_must_be_last_action(self) -> ShortHorizonDecision:
        if any(action.stop for action in self.actions[:-1]):
            raise ValueError("Em ShortHorizonDecision, stop=true só é permitido na última ação do bloco.")
        return self


class BlockValidityResult(BaseModel):
    valid: bool
    reason: str
    invalidated_from_index: int | None = Field(default=None, ge=0)


def normalize_strategy(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


class ReorientationDecision(BaseModel):
    trigger: Literal["stagnation", "action_loop"]
    abandon_strategy: str = Field(min_length=8, max_length=1000)
    new_strategy: str = Field(min_length=8, max_length=1000)
    rationale: str = Field(min_length=8, max_length=2000)

    @model_validator(mode="after")
    def requires_material_strategy_change(self) -> ReorientationDecision:
        if normalize_strategy(self.new_strategy) == normalize_strategy(self.abandon_strategy):
            raise ValueError("new_strategy deve ser diferente de abandon_strategy após normalização.")
        return self


class OrientationSnapshot(BaseModel):
    mission_id: str
    seed: int | None = None
    observations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    action_budget: tuple[int, int] | None = None
    orientation_hash: str = ""


class ProgressSignal(BaseModel):
    progressed: bool
    reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class CognitiveStateSnapshot(BaseModel):
    task_id: str
    objective: str
    current_subgoal_id: int | None = Field(default=None, ge=1)
    completed_subgoals: list[int] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recent_observations: list[str] = Field(default_factory=list)
    failed_strategies: list[str] = Field(default_factory=list)
    active_strategy: str | None = Field(default=None, max_length=1000)
    reorientation_blocked_action_signature: str | None = Field(default=None, max_length=128)
    external_feedback: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    tool_calls_used: int = Field(default=0, ge=0)
    remaining_action_budget: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    iteration: int = Field(default=0, ge=0)
    epistemic_state: EpistemicState | None = None


class ActionObservation(BaseModel):
    tool: str
    ok: bool
    output_summary: str = Field(max_length=2000)
    error: str | None = Field(default=None, max_length=2000)
    verification_passed: bool
    evidence_refs: list[str] = Field(default_factory=list)


class OutcomeResult(BaseModel):
    success: bool
    authority_level: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    final: bool


class Reorientation(BaseModel):
    likely_problem: str = Field(min_length=3, max_length=1000)
    abandon_current_strategy: bool
    next_subgoal: str = Field(min_length=3, max_length=500)


class MemoryCreate(BaseModel):
    type: Literal["working", "episodic", "semantic", "procedural", "self", "world"]
    content: str = Field(min_length=1, max_length=16000)
    summary: str = Field(default="", max_length=1000)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str = Field(default="user", max_length=120)
    provenance: str | None = Field(default=None, max_length=1000)
    task_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class MemoryRead(MemoryCreate):
    id: str
    created_at: datetime
    last_accessed: datetime | None
    access_count: int
    usefulness: float


class MemorySearch(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    types: list[str] = Field(default_factory=list)
    task_id: str | None = None
    limit: int = Field(default=8, ge=1, le=50)


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1000)


class ExperimentCreate(BaseModel):
    hypothesis: str = Field(min_length=5, max_length=4000)
    baseline_version: str = Field(default="production", max_length=120)
    candidate_version: str = Field(min_length=1, max_length=120)
    benchmark: str = Field(min_length=1, max_length=120)


class BenchmarkCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    category: str = Field(min_length=3, max_length=80)
    cases: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("cases")
    @classmethod
    def case_count(cls, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(cases) > 200:
            raise ValueError("O benchmark suporta no máximo 200 casos por definição.")
        return cases


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    task_id: str | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    local: bool
    latency_ms: int
