"""Banco SQLite canônico e operações transacionais do UltronPro."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'active',
    success_metric TEXT,
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.5,
    workspace TEXT NOT NULL,
    autonomy_mode INTEGER NOT NULL DEFAULT 2,
    allowed_tools_json TEXT,
    action_budget_min INTEGER,
    action_budget_max INTEGER,
    requires_external_outcome INTEGER NOT NULL DEFAULT 0,
    step_count INTEGER NOT NULL DEFAULT 0,
    replan_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    llm_call_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id);

CREATE TABLE IF NOT EXISTS task_state (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1,
    objective TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    risks_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, revision)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task_time ON events(task_id, created_at);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.5,
    source TEXT NOT NULL DEFAULT 'system',
    provenance TEXT,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    usefulness REAL NOT NULL DEFAULT 0.5,
    valid_from TEXT,
    valid_until TEXT,
    superseded_by TEXT,
    verification_state TEXT NOT NULL DEFAULT 'legacy',
    verified_writeback_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, summary);

CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    risk TEXT NOT NULL,
    output TEXT,
    error TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    tool_execution_id TEXT REFERENCES tool_executions(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    risk TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    decision_note TEXT
);

CREATE TABLE IF NOT EXISTS task_continuations (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    approval_id TEXT NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,
    tool_execution_id TEXT NOT NULL REFERENCES tool_executions(id) ON DELETE CASCADE,
    plan_revision INTEGER NOT NULL,
    step_index INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting_approval',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_continuations_status ON task_continuations(status, updated_at);

CREATE TABLE IF NOT EXISTS execution_traces (
    id TEXT PRIMARY KEY,
    execution_trace_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    plan_revision INTEGER,
    step_id INTEGER,
    tool_execution_id TEXT REFERENCES tool_executions(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    router_decision_ids_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_traces_task ON execution_traces(task_id, created_at);

CREATE TABLE IF NOT EXISTS cognitive_snapshots (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL,
    current_subgoal_id INTEGER,
    completed_subgoals_json TEXT NOT NULL DEFAULT '[]',
    known_facts_json TEXT NOT NULL DEFAULT '[]',
    open_questions_json TEXT NOT NULL DEFAULT '[]',
    recent_observations_json TEXT NOT NULL DEFAULT '[]',
    failed_strategies_json TEXT NOT NULL DEFAULT '[]',
    active_strategy TEXT,
    reorientation_blocked_action_signature TEXT,
    external_feedback_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    tool_calls_used INTEGER NOT NULL DEFAULT 0,
    remaining_action_budget INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, iteration)
);
CREATE INDEX IF NOT EXISTS idx_cognitive_snapshots_task_iteration ON cognitive_snapshots(task_id, iteration DESC);

CREATE TABLE IF NOT EXISTS cognitive_actions (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL,
    subgoal_id INTEGER,
    tool TEXT,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    expected_evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    model TEXT,
    seed INTEGER,
    created_at TEXT NOT NULL,
    executed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cognitive_actions_task_iteration ON cognitive_actions(task_id, iteration, created_at);

CREATE TABLE IF NOT EXISTS structured_decisions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    controller_mode TEXT NOT NULL,
    decision_kind TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    initial_valid INTEGER NOT NULL,
    final_valid INTEGER NOT NULL,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    validation_error_class TEXT,
    error_category TEXT,
    model TEXT,
    seed INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_decisions_task ON structured_decisions(task_id, created_at);

CREATE TABLE IF NOT EXISTS horizon_orientations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    orientation_hash TEXT NOT NULL,
    observations_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, mission_id, seed)
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    trigger_json TEXT NOT NULL DEFAULT '[]',
    procedure_json TEXT NOT NULL DEFAULT '[]',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    last_used TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    verification_state TEXT NOT NULL DEFAULT 'pending',
    verified_writeback_id TEXT
);

CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    strategy TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    result TEXT NOT NULL,
    success INTEGER NOT NULL,
    errors_json TEXT NOT NULL DEFAULT '[]',
    lessons_json TEXT NOT NULL DEFAULT '[]',
    quality REAL NOT NULL DEFAULT 0.5,
    verification_state TEXT NOT NULL DEFAULT 'pending',
    verified_writeback_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verified_writebacks (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    outcome_success INTEGER NOT NULL,
    outcome_final INTEGER NOT NULL,
    authority_level TEXT NOT NULL,
    minimum_authority TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verified_writebacks_target ON verified_writebacks(target_type, target_id, allowed, created_at DESC);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    baseline_score REAL,
    candidate_score REAL,
    regression_score REAL,
    status TEXT NOT NULL DEFAULT 'draft',
    report TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    latest_score REAL,
    runs INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL REFERENCES benchmarks(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,
    total INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    model_name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    latency_ms INTEGER,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    finish_reason TEXT,
    seed INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    benchmark TEXT NOT NULL,
    benchmark_version TEXT NOT NULL,
    mode TEXT NOT NULL,
    model_name TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    git_commit TEXT NOT NULL,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,
    total INTEGER NOT NULL,
    recovery_rate REAL NOT NULL DEFAULT 0,
    average_steps REAL NOT NULL DEFAULT 0,
    average_tool_calls REAL NOT NULL DEFAULT 0,
    average_latency_ms REAL NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    artifact_dir TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_runs_benchmark_time ON research_runs(benchmark, created_at);

CREATE TABLE IF NOT EXISTS research_task_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    category TEXT NOT NULL,
    success INTEGER NOT NULL,
    score REAL NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    execution_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, task_id)
);

CREATE TABLE IF NOT EXISTS memory_retrievals (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    memory_ids_json TEXT NOT NULL DEFAULT '[]',
    scores_json TEXT NOT NULL DEFAULT '[]',
    selected INTEGER NOT NULL DEFAULT 1,
    used_by_agent INTEGER NOT NULL DEFAULT 0,
    result_success INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnostic_runs (
    id TEXT PRIMARY KEY,
    experiment TEXT NOT NULL,
    hypothesis_id TEXT,
    model_name TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    artifact_dir TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnostic_runs_experiment_time ON diagnostic_runs(experiment, created_at);

CREATE TABLE IF NOT EXISTS memory_write_decisions (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    should_write INTEGER NOT NULL,
    memory_type TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    utility_prediction REAL NOT NULL,
    generalizability REAL NOT NULL,
    evidence_strength REAL NOT NULL,
    admission_score REAL NOT NULL,
    reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_write_decisions_time ON memory_write_decisions(created_at);

CREATE TABLE IF NOT EXISTS task_signatures (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    family TEXT NOT NULL,
    domain TEXT NOT NULL,
    required_tools_json TEXT NOT NULL DEFAULT '[]',
    failure_class TEXT,
    artifact_type TEXT,
    operation_kind TEXT,
    difficulty TEXT,
    uncertainty REAL NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_signatures_family ON task_signatures(family, created_at);

CREATE TABLE IF NOT EXISTS experience_signatures (
    id TEXT PRIMARY KEY,
    experience_id TEXT NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    family TEXT NOT NULL,
    domain TEXT NOT NULL,
    failure_classes_json TEXT NOT NULL DEFAULT '[]',
    tool_families_json TEXT NOT NULL DEFAULT '[]',
    abstraction_level REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    historical_utility REAL NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experience_signatures_family ON experience_signatures(family, verified, historical_utility);

CREATE TABLE IF NOT EXISTS experience_pair_utility (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    task_signature_id TEXT NOT NULL REFERENCES task_signatures(id) ON DELETE CASCADE,
    experience_id TEXT NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    task_id TEXT,
    task_family TEXT,
    experience_family TEXT,
    source_domain TEXT,
    target_domain TEXT,
    fresh_score REAL NOT NULL,
    experienced_score REAL NOT NULL,
    paired_delta REAL NOT NULL,
    seed INTEGER,
    model_name TEXT,
    prompt_version TEXT,
    dataset_split TEXT NOT NULL DEFAULT 'legacy',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pair_utility_experience ON experience_pair_utility(experience_id, created_at);

CREATE TABLE IF NOT EXISTS routing_decisions (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    task_family TEXT NOT NULL,
    experience_id TEXT REFERENCES experiences(id) ON DELETE SET NULL,
    compatibility REAL NOT NULL,
    expected_utility REAL NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    observed_score REAL,
    observed_utility REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_family ON routing_decisions(task_family, decision, created_at);

CREATE TABLE IF NOT EXISTS family_utility_map (
    task_family TEXT NOT NULL,
    experience_family TEXT NOT NULL,
    mean_delta REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    ci95_low REAL,
    ci95_high REAL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (task_family, experience_family)
);

CREATE TABLE IF NOT EXISTS distilled_procedures (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    principle TEXT NOT NULL,
    preconditions_json TEXT NOT NULL DEFAULT '[]',
    recommended_actions_json TEXT NOT NULL,
    avoid_actions_json TEXT NOT NULL DEFAULT '[]',
    source_experience_ids_json TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    success_count INTEGER NOT NULL,
    failure_count INTEGER NOT NULL,
    mean_utility REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_distilled_procedures_family ON distilled_procedures(family, mean_utility);

CREATE TABLE IF NOT EXISTS skill_family_utility (
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    family TEXT NOT NULL,
    mean_delta REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (skill_id, family)
);

CREATE TABLE IF NOT EXISTS utility_predictions (
    id TEXT PRIMARY KEY,
    routing_decision_id TEXT NOT NULL REFERENCES routing_decisions(id) ON DELETE CASCADE,
    predicted_utility REAL NOT NULL,
    observed_utility REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_runs (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    model_name TEXT NOT NULL,
    seed INTEGER NOT NULL,
    fresh_score REAL NOT NULL,
    experienced_score REAL NOT NULL,
    transfer_gain REAL NOT NULL,
    artifact_dir TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_estimates (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    task_type TEXT NOT NULL,
    successes INTEGER NOT NULL,
    failures INTEGER NOT NULL,
    success_rate REAL NOT NULL,
    calibrated_score REAL NOT NULL,
    uncertainty REAL NOT NULL,
    sample_size INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(domain, task_type)
);

CREATE TABLE IF NOT EXISTS world_model_observations (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    predicted_success REAL NOT NULL,
    predicted_outcome TEXT NOT NULL,
    actual_success INTEGER NOT NULL,
    actual_outcome TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_model_observations_action_time ON world_model_observations(action, created_at);

CREATE TABLE IF NOT EXISTS retrieval_traces (
    id TEXT PRIMARY KEY,
    retrieval_id TEXT REFERENCES memory_retrievals(id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    candidates_json TEXT NOT NULL DEFAULT '[]',
    selected_json TEXT NOT NULL DEFAULT '[]',
    prompt_positions_json TEXT NOT NULL DEFAULT '[]',
    prompt_included_json TEXT NOT NULL DEFAULT '[]',
    result_success INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retrieval_traces_task_time ON retrieval_traces(task_id, created_at);

CREATE TABLE IF NOT EXISTS context_metrics (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    purpose TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    total_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    success INTEGER,
    steps INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_utility_observations (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    with_memory_score REAL,
    without_memory_score REAL,
    delta REAL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_utility_memory ON memory_utility_observations(memory_id, created_at);

CREATE TABLE IF NOT EXISTS failures (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    tool TEXT,
    recoverable INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    recovery_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 0.5,
    provenance TEXT,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assertions (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    evidence TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    source_type TEXT,
    source_uri TEXT,
    observed_at TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT
);
"""


MODEL_CALL_MIGRATIONS = {
    "seed": "INTEGER",
}

TASK_CONTRACT_MIGRATIONS = {
    "allowed_tools_json": "TEXT",
    "action_budget_min": "INTEGER",
    "action_budget_max": "INTEGER",
    "requires_external_outcome": "INTEGER NOT NULL DEFAULT 0",
}

MEMORY_VERIFICATION_MIGRATIONS = {
    "verification_state": "TEXT NOT NULL DEFAULT 'legacy'",
    "verified_writeback_id": "TEXT",
}

EXPERIENCE_VERIFICATION_MIGRATIONS = {
    "verification_state": "TEXT NOT NULL DEFAULT 'pending'",
    "verified_writeback_id": "TEXT",
}

SKILL_VERIFICATION_MIGRATIONS = {
    "verification_state": "TEXT NOT NULL DEFAULT 'pending'",
    "verified_writeback_id": "TEXT",
}


STRUCTURED_DECISION_MIGRATIONS = {
    "error_category": "TEXT",
}

COGNITIVE_SNAPSHOT_MIGRATIONS = {
    "active_strategy": "TEXT",
    "reorientation_blocked_action_signature": "TEXT",
    "external_feedback_json": "TEXT NOT NULL DEFAULT '[]'",
}


PAIR_UTILITY_MIGRATIONS = {
    "task_id": "TEXT",
    "task_family": "TEXT",
    "experience_family": "TEXT",
    "source_domain": "TEXT",
    "target_domain": "TEXT",
    "seed": "INTEGER",
    "model_name": "TEXT",
    "prompt_version": "TEXT",
    "dataset_split": "TEXT NOT NULL DEFAULT 'legacy'",
}


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            model_call_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(model_calls)")}
            for name, definition in MODEL_CALL_MIGRATIONS.items():
                if name not in model_call_columns:
                    connection.execute(f"ALTER TABLE model_calls ADD COLUMN {name} {definition}")
            task_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tasks)")}
            for name, definition in TASK_CONTRACT_MIGRATIONS.items():
                if name not in task_columns:
                    connection.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            structured_decision_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(structured_decisions)")}
            for name, definition in STRUCTURED_DECISION_MIGRATIONS.items():
                if name not in structured_decision_columns:
                    connection.execute(f"ALTER TABLE structured_decisions ADD COLUMN {name} {definition}")
            cognitive_snapshot_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(cognitive_snapshots)")}
            for name, definition in COGNITIVE_SNAPSHOT_MIGRATIONS.items():
                if name not in cognitive_snapshot_columns:
                    connection.execute(f"ALTER TABLE cognitive_snapshots ADD COLUMN {name} {definition}")
            memory_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(memories)")}
            for name, definition in MEMORY_VERIFICATION_MIGRATIONS.items():
                if name not in memory_columns:
                    connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
            experience_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(experiences)")}
            for name, definition in EXPERIENCE_VERIFICATION_MIGRATIONS.items():
                if name not in experience_columns:
                    connection.execute(f"ALTER TABLE experiences ADD COLUMN {name} {definition}")
            skill_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(skills)")}
            for name, definition in SKILL_VERIFICATION_MIGRATIONS.items():
                if name not in skill_columns:
                    connection.execute(f"ALTER TABLE skills ADD COLUMN {name} {definition}")
            pair_utility_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(experience_pair_utility)")}
            for name, definition in PAIR_UTILITY_MIGRATIONS.items():
                if name not in pair_utility_columns:
                    connection.execute(f"ALTER TABLE experience_pair_utility ADD COLUMN {name} {definition}")

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def execute_many(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        with self.connect() as connection:
            connection.executemany(sql, params)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return self._row(row)

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row(row) for row in rows if row is not None]

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def parse_json(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None
