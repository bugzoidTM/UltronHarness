from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.research.cycle import ExperienceCycle, SkillService
from ultron.schemas import (
    CognitiveStateSnapshot,
    MissionOutline,
    MissionSubgoal,
    NextAction,
    OutcomeResult,
    VerificationSpec,
)

ROOT = Path(__file__).resolve().parents[1]


def test_horizon_outline_and_snapshot_roundtrip() -> None:
    outline = MissionOutline(
        objective="Reparar módulo local com evidência verificável.",
        subgoals=[MissionSubgoal(id=1, description="Inspecionar arquivos"), MissionSubgoal(id=2, description="Validar correção")],
    )
    snapshot = CognitiveStateSnapshot(
        task_id="task-1",
        objective=outline.objective,
        current_subgoal_id=1,
        known_facts=["arquivo config.py existe"],
        recent_observations=["file.list retornou config.py"],
        evidence_refs=["trace-1"],
        tool_calls_used=1,
        remaining_action_budget=11,
        iteration=1,
    )

    assert MissionOutline.model_validate_json(outline.model_dump_json()) == outline
    assert CognitiveStateSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_next_action_schema_rejects_stop_reason_without_stop() -> None:
    with pytest.raises(ValidationError):
        NextAction(
            intent="Continuar inspeção",
            expected_evidence=VerificationSpec(type="task_context"),
            stop_reason="Ainda não concluído",
        )


def test_horizon_database_initializes_append_only_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "ultron.db")
    db.initialize()

    assert db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='cognitive_snapshots'")
    assert db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='cognitive_actions'")
    columns = {row["name"] for row in db.all("PRAGMA table_info(memories)")}
    assert "verification_state" in columns


def test_private_evaluator_overrides_internal_success_and_writeback(tmp_path: Path) -> None:
    authority = OutcomeAuthority()
    result = authority.decide(
        private_evaluation={"passed": False, "evidence": ["missing deliverable"]},
        tool_succeeded=True,
        model_claim=True,
    )
    assert result.success is False
    assert result.authority_level == "private_mission_evaluator"
    assert result.final is True

    settings = Settings(raw=load_settings(ROOT).raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    cycle = ExperienceCycle(db, SkillService(db))
    writeback = cycle.consolidate(
        "Criar artefato",
        "runtime interno concluiu",
        ["validar com evaluator"],
        success=True,
        outcome_result=result,
    )
    assert writeback["stored"] is False
    assert writeback["verification_state"] == "rejected"


def test_external_success_allows_verified_writeback(tmp_path: Path) -> None:
    authority = OutcomeAuthority()
    result = authority.decide(private_evaluation={"passed": True, "evidence": ["contract-pass"]})
    assert OutcomeAuthority.allows_verified_writeback(result)
    assert result == OutcomeResult(
        success=True,
        authority_level="private_mission_evaluator",
        evidence_refs=["contract-pass"],
        confidence=1.0,
        final=True,
    )
