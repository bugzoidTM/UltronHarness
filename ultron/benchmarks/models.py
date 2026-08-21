"""Contratos estritos do benchmark UGIB-Lite e de seus artefatos de execução."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

BenchmarkMode = Literal["baseline", "tools", "ultron-fresh", "ultron-experienced"]


class BenchmarkTask(BaseModel):
    """Contrato público entregue ao agente; não contém gabarito ou avaliador privado."""

    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    category: Literal["reasoning", "coding", "tool_use", "recovery"]
    objective: str = Field(min_length=8, max_length=8000)
    workspace_fixture: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    expected_artifacts: list[str] = Field(default_factory=list)
    evaluator: str = Field(min_length=3, max_length=120)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    max_steps: int = Field(default=1, ge=1, le=100)
    hidden: bool = False


class EvaluationResult(BaseModel):
    success: bool
    score: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)


class TaskExecution(BaseModel):
    task_id: str
    mode: BenchmarkMode
    response: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    failure_category: str | None = None
    recovered: bool = False
    steps: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    context_metrics: dict[str, int] = Field(default_factory=dict)
    model: str


class TaskRunResult(BaseModel):
    task: BenchmarkTask
    execution: TaskExecution
    evaluation: EvaluationResult


class RunManifest(BaseModel):
    run_id: str
    git_commit: str
    model: str
    model_hash: str | None = None
    quantization: str | None = None
    runtime: str
    benchmark: str
    benchmark_version: str
    mode: BenchmarkMode
    seed: int
    config_hash: str
    started_at: datetime
    completed_at: datetime | None = None
    platform: dict[str, Any]


class BenchmarkRunSummary(BaseModel):
    run_id: str
    benchmark: str
    mode: BenchmarkMode
    score: float = Field(ge=0.0, le=1.0)
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    recovery_rate: float = Field(ge=0.0, le=1.0)
    first_attempt_success_rate: float = Field(ge=0.0, le=1.0)
    average_steps: float = Field(ge=0.0)
    average_tool_calls: float = Field(ge=0.0)
    average_latency_ms: float = Field(ge=0.0)
    memory_reuse_rate: float = Field(ge=0.0, le=1.0)
    skill_reuse_rate: float = Field(ge=0.0, le=1.0)
    results: list[TaskRunResult] = Field(default_factory=list)


class ModelBenchmarkResult(BaseModel):
    model: str
    score: float = Field(ge=0.0, le=1.0)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    invalid_output_rate: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    tokens_per_second: float | None = None
    ram_peak_mb: float | None = None
    vram_peak_mb: float | None = None
