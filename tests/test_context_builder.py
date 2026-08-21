from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.learning.context_builder import ContextBuilder
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder

ROOT = Path(__file__).resolve().parents[1]


def _task(db: Database, task_id: str, objective: str, family: str = "planning") -> dict:
    now = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, task_id, objective, "created", 0.5, "default", 2, now, now),
    )
    return {
        "id": task_id,
        "title": task_id,
        "objective": objective,
        "family": family,
        "category": "reasoning",
        "target_domain": "runtime-test",
        "required_tools": ["file.write"],
    }


def _db(tmp_path: Path) -> Database:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    return db


def test_context_builder_abstains_without_paired_evidence_and_persists_outcome(tmp_path: Path) -> None:
    db = _db(tmp_path)
    prior_task = _task(db, "prior", "Planejar workflow com pré-condição", "planning")
    experience_id = "experience-prior"
    db.execute(
        "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (experience_id, prior_task["id"], "structured-plan", "[]", "Sucesso", 1, "[]", '["Validar pré-condição antes de executar."]', 0.9, datetime.now(UTC).isoformat()),
    )
    ExperienceSignatureBuilder.persist(
        db,
        ExperienceSignature(category="reasoning", family="planning", domain="runtime-test", tool_families=["file.write"], abstraction_level=0.8, verified=True),
        experience_id,
    )
    task = _task(db, "target", "Planejar workflow e validar dependência", "planning")
    builder = ContextBuilder(db)
    context = builder.build(task)
    assert context.candidate_count == 1
    assert not context.injected
    decision = db.one("SELECT decision,reason FROM routing_decisions WHERE task_id=?", (task["id"],))
    assert decision == {"decision": "ABSTAIN", "reason": "insufficient_paired_evidence"}

    completed_experience = "experience-target"
    db.execute(
        "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (completed_experience, task["id"], "structured-plan", "[]", "Sucesso", 1, "[]", "[]", 0.9, datetime.now(UTC).isoformat()),
    )
    builder.record_outcome(task["id"], context, success=True, experience_id=completed_experience)
    observed = db.one("SELECT observed_score FROM routing_decisions WHERE task_id=?", (task["id"],))
    assert observed == {"observed_score": 1.0}
    created_signature = db.one("SELECT verified,family FROM experience_signatures WHERE experience_id=?", (completed_experience,))
    assert created_signature == {"verified": 1, "family": "planning"}
    utility = db.one("SELECT state,sample_count FROM family_utility_map WHERE task_family='planning' AND experience_family='planning'")
    assert utility == {"state": "INSUFFICIENT_DATA", "sample_count": 0}


def test_candidate_prefilter_preserves_relevant_experience_and_applies_match_budget(tmp_path: Path) -> None:
    db = _db(tmp_path)
    task = _task(db, "retrieval-target", "Planejar workflow com dependências", "planning")
    relevant_id = "experience-relevant"
    for index in range(12):
        experience_id = relevant_id if index == 0 else f"experience-planning-{index}"
        db.execute(
            "INSERT INTO experiences (id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (experience_id, "procedure", "[]", f"Resultado {index}", 1, "[]", f'["Lição distinta {index}"]', 0.8, datetime.now(UTC).isoformat()),
        )
        ExperienceSignatureBuilder.persist(
            db,
            ExperienceSignature(category="reasoning", family="planning", domain="runtime-test", tool_families=["file.write"], abstraction_level=0.8, verified=True),
            experience_id,
        )
    builder = ContextBuilder(db, prefilter_limit=50, match_limit=10, injection_limit=2)
    assert builder.candidate_recall(task, relevant_id)
    context = builder.build(task)
    assert context.prefilter_count == 12
    assert context.candidate_count == 10
    assert not context.injected
