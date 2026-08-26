from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

GENESIS_PROTOCOL_VERSION = "genesis-v0.2-cognitive-vm"
GENESIS_MAX_PROGRAMS = 2
GENESIS_MAX_OPERATORS = 4

GenesisOperator = Literal[
    "REPRESENT",
    "DECOMPOSE",
    "HYPOTHESIZE",
    "DEDUCT",
    "VERIFY",
    "BACKTRACK",
]

GENESIS_OPERATORS: tuple[str, ...] = (
    "REPRESENT",
    "DECOMPOSE",
    "HYPOTHESIZE",
    "DEDUCT",
    "VERIFY",
    "BACKTRACK",
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
    facts: list[str] = Field(default_factory=list, max_length=32)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    hypotheses: list[str] = Field(default_factory=list, max_length=16)
    predictions: list[str] = Field(default_factory=list, max_length=16)
    candidate_answer: str | None = Field(default=None, max_length=256)
    verification: dict[str, str] = Field(default_factory=dict, max_length=16)
    trace: list[dict[str, str]] = Field(default_factory=list, max_length=32)


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
