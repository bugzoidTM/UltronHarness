from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

GENESIS_PROTOCOL_VERSION = "genesis-v0.2.2-non-solving"
GENESIS_V1_PROTOCOL_VERSION = "genesis-v1-adaptive-policy"
GENESIS_MAX_PROGRAMS = 2
GENESIS_MAX_OPERATORS = 4

GenesisOperator = Literal["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"]

GENESIS_OPERATORS: tuple[str, ...] = (
    "REPRESENT",
    "HYPOTHESIZE",
    "DEDUCT",
    "VERIFY",
)


class CognitiveProgram(BaseModel):
    """Programa temporário de operadores; rationale é metadado somente de auditoria."""

    id: str = Field(pattern=r"^CP-[A-Z0-9_-]{1,32}$", max_length=36)
    operators: list[GenesisOperator] = Field(min_length=1, max_length=GENESIS_MAX_OPERATORS)
    rationale: str = Field(min_length=8, max_length=1200)
    generation_source: Literal["model_generated"] = "model_generated"

    @model_validator(mode="after")
    def validate_program_shape(self) -> CognitiveProgram:
        if "STOP" in self.operators:
            raise ValueError("stop_is_not_a_vm_operator")
        return self


class CognitiveProgramBatch(BaseModel):
    programs: list[CognitiveProgram] = Field(min_length=1, max_length=GENESIS_MAX_PROGRAMS)

    @model_validator(mode="after")
    def validate_unique_programs(self) -> CognitiveProgramBatch:
        ids = [program.id for program in self.programs]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_program_ids")
        return self


class CognitiveFrame(BaseModel):
    problem: str = Field(min_length=1, max_length=8000)
    entities: list[str] = Field(default_factory=list, max_length=32)
    facts: list[str] = Field(default_factory=list, max_length=32)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    hypotheses: list[str] = Field(default_factory=list, max_length=16)
    predictions: list[str] = Field(default_factory=list, max_length=16)
    candidate_answer: str | None = Field(default=None, max_length=256)
    verification: dict[str, str] = Field(default_factory=dict, max_length=16)
    trace: list[dict[str, str]] = Field(default_factory=list, max_length=32)


class RepresentationOutput(BaseModel):
    entities: list[str] = Field(default_factory=list, max_length=16)
    facts: list[str] = Field(default_factory=list, max_length=16)
    constraints: list[str] = Field(default_factory=list, max_length=16)
    unknowns: list[str] = Field(default_factory=list, max_length=8)


class HypothesisOutput(BaseModel):
    hypotheses: list[str] = Field(default_factory=list, max_length=8)
    predictions: list[str] = Field(default_factory=list, max_length=8)


class DeductionOutput(BaseModel):
    conclusion: str = Field(min_length=1, max_length=256)


class VerificationOutput(BaseModel):
    status: Literal["supported", "contradicted", "uncertain"]
    explanation: str = Field(min_length=1, max_length=512)


PolicyCondition = Literal[
    "no_representation",
    "has_facts",
    "no_hypothesis",
    "has_hypothesis",
    "no_candidate",
    "has_candidate",
    "verification_supported",
    "verification_contradicted",
    "verification_uncertain",
]


class CognitivePolicyRule(BaseModel):
    conditions: list[PolicyCondition] = Field(min_length=1, max_length=3)
    operator: GenesisOperator
    priority: int = Field(ge=0, le=63)


class CognitivePolicy(BaseModel):
    """Política finita de transições; a condição supported encerra fora da lista de operadores."""

    id: str = Field(pattern=r"^CP-[A-Z0-9_-]{1,32}$", max_length=36)
    rules: list[CognitivePolicyRule] = Field(min_length=1, max_length=8)
    max_decisions: int = Field(default=6, ge=1, le=6)
    rationale: str = Field(min_length=8, max_length=1200)
    generation_source: Literal["model_generated"] = "model_generated"

    @model_validator(mode="after")
    def validate_policy_shape(self) -> CognitivePolicy:
        priorities = [rule.priority for rule in self.rules]
        if len(set(priorities)) != len(priorities):
            raise ValueError("duplicate_policy_priorities")
        initial_conditions = {"no_representation", "no_hypothesis", "no_candidate"}
        if not any(initial_conditions.intersection(rule.conditions) for rule in self.rules):
            raise ValueError("policy_has_no_initial_transition")
        if not any(rule.priority == 0 and "no_representation" in rule.conditions and rule.operator == "REPRESENT" for rule in self.rules):
            raise ValueError("policy_must_start_with_representation")
        required_conditions = {"no_hypothesis", "no_candidate", "has_candidate"}
        available_conditions = {condition for rule in self.rules for condition in rule.conditions}
        if not required_conditions.issubset(available_conditions):
            raise ValueError("policy_missing_progress_condition")
        feedback_conditions = {"verification_contradicted", "verification_uncertain"}
        if not feedback_conditions.issubset(available_conditions):
            raise ValueError("policy_missing_feedback_condition")
        for rule in self.rules:
            if "no_representation" in rule.conditions and rule.operator != "REPRESENT":
                raise ValueError("no_representation_requires_represent")
            if "no_hypothesis" in rule.conditions and rule.operator != "HYPOTHESIZE":
                raise ValueError("no_hypothesis_requires_hypothesize")
            if "no_candidate" in rule.conditions and rule.operator != "DEDUCT":
                raise ValueError("no_candidate_requires_deduct")
            if "has_candidate" in rule.conditions and rule.operator != "VERIFY":
                raise ValueError("has_candidate_requires_verify")
            if feedback_conditions.intersection(rule.conditions) and rule.operator not in {"HYPOTHESIZE", "DEDUCT"}:
                raise ValueError("feedback_requires_revision_operator")
        return self


class DeliberationOutput(BaseModel):
    note: str = Field(min_length=1, max_length=1000)
    candidate_answer: str = Field(default="", max_length=256)


class FinalAnswerOutput(BaseModel):
    answer: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class GenesisSummary:
    run_id: str
    status: str
    reason: str
    experiment_id: str
    diagnosis_task_ids: tuple[str, ...] = ()
    holdout_task_ids: tuple[str, ...] = ()
    program_ids: tuple[str, ...] = ()
    selected_program_id: str | None = None
    baseline_holdout_score: float | None = None
    selected_holdout_score: float | None = None
    ncpg: float | None = None
    executions: int = 0
    writeback_id: str | None = None
    retained: bool = False

    @property
    def promoted(self) -> bool:
        return bool(self.writeback_id and self.status == "promoted")
