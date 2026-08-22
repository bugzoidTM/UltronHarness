from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.learning.context_builder import ContextBuilder
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.memory.service import MemoryService
from ultron.schemas import MemoryCreate, MemorySearch, OutcomeResult

ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path: Path) -> tuple[Database, Settings]:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["memory"]["vector_enabled"] = False
    db = Database(settings.db_path)
    db.initialize()
    return db, settings


def _task(db: Database, task_id: str, *, family: str = "planning") -> dict:
    now = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, task_id, "Planejar uma correção local verificável", "created", 0.5, "default", 2, now, now),
    )
    return {
        "id": task_id,
        "title": task_id,
        "objective": "Planejar uma correção local verificável",
        "family": family,
        "category": "reasoning",
        "target_domain": "runtime-test",
        "required_tools": ["file.write"],
    }


def _outcome(*, success: bool, authority: str = "private_mission_evaluator", final: bool = True) -> OutcomeResult:
    return OutcomeResult(
        success=success,
        authority_level=authority,
        evidence_refs=["outcome-ref"],
        confidence=1.0,
        final=final,
    )


def _insert_experience(db: Database, experience_id: str, task_id: str) -> None:
    db.execute(
        "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (experience_id, task_id, "structured-plan", "[]", "Sucesso", 1, "[]", '["Validar pré-condição antes de executar."]', 0.9, datetime.now(UTC).isoformat()),
    )


def test_verified_writeback_requires_final_success_and_minimum_authority(tmp_path: Path) -> None:
    db, _ = _db(tmp_path)
    gate = VerifiedWritebackGate(db, minimum_authority="private_mission_evaluator")

    no_outcome = gate.evaluate(task_id="missing", target_type="experience", target_id="one", outcome_result=None)
    internal_pass = gate.evaluate(
        task_id="internal",
        target_type="experience",
        target_id="two",
        outcome_result=_outcome(success=True, authority="task_registered_verifier"),
    )
    evaluator_fail = gate.evaluate(
        task_id="failed",
        target_type="experience",
        target_id="three",
        outcome_result=_outcome(success=False),
    )
    evaluator_pass = gate.evaluate(
        task_id="passed",
        target_type="experience",
        target_id="four",
        outcome_result=_outcome(success=True),
    )

    assert (no_outcome.allowed, no_outcome.reason) == (False, "final_outcome_required")
    assert (internal_pass.allowed, internal_pass.reason) == (False, "outcome_authority_insufficient")
    assert (evaluator_fail.allowed, evaluator_fail.reason) == (False, "outcome_failed")
    assert (evaluator_pass.allowed, evaluator_pass.reason) == (True, "verified_outcome_authorized")
    assert db.one("SELECT COUNT(*) AS count FROM verified_writebacks") == {"count": 4}


def test_experience_cannot_be_verified_or_reused_without_authorized_writeback(tmp_path: Path) -> None:
    db, _ = _db(tmp_path)
    prior = _task(db, "prior")
    _insert_experience(db, "experience-prior", prior["id"])
    signature = ExperienceSignature(
        category="reasoning",
        family="planning",
        domain="runtime-test",
        tool_families=["file.write"],
        abstraction_level=0.8,
        verified=True,
    )

    with pytest.raises(ValueError, match="verified writeback autorizado"):
        ExperienceSignatureBuilder.persist(db, signature, "experience-prior")

    target = _task(db, "target")
    builder = ContextBuilder(db)
    context = builder.build(target)
    builder.record_outcome(target["id"], context, success=True, experience_id="experience-prior", outcome_result=_outcome(success=False))
    assert db.one("SELECT verified_writeback_id FROM experiences WHERE id='experience-prior'") == {"verified_writeback_id": None}
    assert builder.build(target).candidate_count == 0


def test_private_pass_promotes_experience_and_only_then_allows_context_candidate(tmp_path: Path) -> None:
    db, _ = _db(tmp_path)
    prior = _task(db, "prior")
    _insert_experience(db, "experience-prior", prior["id"])
    target = _task(db, "target")
    builder = ContextBuilder(db)
    context = builder.build(target)
    builder.record_outcome(target["id"], context, success=True, experience_id="experience-prior", outcome_result=_outcome(success=True))

    promoted = db.one("SELECT verification_state,verified_writeback_id FROM experiences WHERE id='experience-prior'")
    assert promoted["verification_state"] == "verified"
    assert promoted["verified_writeback_id"]
    assert builder.build(target).candidate_count == 1


def test_procedural_memory_does_not_feed_retrieval_until_verified_writeback(tmp_path: Path) -> None:
    db, settings = _db(tmp_path)
    memory = MemoryService(db, settings)
    created = memory.create(
        MemoryCreate(
            type="procedural",
            content="Validar precondicao antes de executar a mudança.",
            summary="Validar precondicao",
            importance=0.8,
            confidence=0.8,
            source="consolidation",
        )
    )
    request = MemorySearch(query="precondicao", limit=5, types=["procedural"])
    assert memory.search(request) == []

    decision = VerifiedWritebackGate(db).evaluate(
        task_id=None,
        target_type="memory",
        target_id=created["id"],
        outcome_result=_outcome(success=True),
    )
    assert decision.allowed
    db.execute(
        "UPDATE memories SET verification_state='verified', verified_writeback_id=? WHERE id=?",
        (decision.audit_id, created["id"]),
    )
    assert [item["id"] for item in memory.search(request)] == [created["id"]]



def test_experience_cycle_writes_skill_only_after_authorized_final_outcome(tmp_path: Path) -> None:
    from ultron.research.cycle import ExperienceCycle, SkillService

    db, _ = _db(tmp_path)
    cycle = ExperienceCycle(db, SkillService(db))
    denied = cycle.consolidate(
        "Criar procedimento verificável",
        "modelo declarou sucesso",
        ["Validar o artefato antes de reutilizar o procedimento."],
        success=True,
        outcome_result=None,
    )
    assert denied["stored"] is False
    assert denied["reason"] == "final_outcome_required"
    assert db.one("SELECT COUNT(*) AS count FROM skills") == {"count": 0}

    accepted = cycle.consolidate(
        "Criar procedimento verificável",
        "evaluator aprovou a entrega",
        ["Validar o artefato antes de reutilizar o procedimento."],
        success=True,
        outcome_result=_outcome(success=True),
    )
    assert accepted["stored"] is True
    skill = db.one("SELECT verification_state,verified_writeback_id FROM skills WHERE id=?", (accepted["skill_id"],))
    assert skill["verification_state"] == "verified"
    assert skill["verified_writeback_id"] == accepted["writeback_audit_id"]
