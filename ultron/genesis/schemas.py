from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

GENESIS_PROTOCOL_VERSION = "genesis-v0.1"
GENESIS_MAX_PROGRAMS = 3
GENESIS_MAX_OPERATORS = 6

GenesisOperator = Literal[
    "OBSERVE",
    "IDENTIFY_UNKNOWN",
    "REPRESENT",
    "DECOMPOSE",
    "HYPOTHESIZE",
    "COMPARE",
    "PREDICT",
    "TEST",
    "DEDUCT",
    "BACKTRACK",
    "VERIFY",
    "UPDATE_BELIEF",
    "STOP",
]

GENESIS_OPERATORS: tuple[str, ...] = (
    "OBSERVE",
    "IDENTIFY_UNKNOWN",
    "REPRESENT",
    "DECOMPOSE",
    "HYPOTHESIZE",
    "COMPARE",
    "PREDICT",
    "TEST",
    "DEDUCT",
    "BACKTRACK",
    "VERIFY",
    "UPDATE_BELIEF",
    "STOP",
)


class CognitiveProgram(BaseModel):
    """Programa temporário interpretável; não contém código executável."""

    id: str = Field(pattern=r"^CP-[A-Z0-9_-]{1,32}$", max_length=36)
    operators: list[GenesisOperator] = Field(min_length=1, max_length=GENESIS_MAX_OPERATORS)
    rationale: str = Field(min_length=8, max_length=1200)
    generation_source: Literal["model_generated"] = "model_generated"

    @model_validator(mode="after")
    def validate_program_shape(self) -> CognitiveProgram:
        if len(set(self.operators)) != len(self.operators):
            raise ValueError("duplicate_operators")
        if "STOP" in self.operators[:-1]:
            raise ValueError("stop_must_be_last")
        if self.operators[-1] != "STOP":
            raise ValueError("stop_required_last")
        return self


class CognitiveProgramBatch(BaseModel):
    programs: list[CognitiveProgram] = Field(min_length=1, max_length=GENESIS_MAX_PROGRAMS)

    @model_validator(mode="after")
    def validate_unique_programs(self) -> CognitiveProgramBatch:
        ids = [program.id for program in self.programs]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_program_ids")
        signatures = [tuple(program.operators) for program in self.programs]
        if len(set(signatures)) != len(signatures):
            raise ValueError("duplicate_program_signatures")
        return self


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
