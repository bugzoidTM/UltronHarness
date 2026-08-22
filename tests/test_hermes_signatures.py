from __future__ import annotations

from ultron.cognition.task_signature import TaskSignatureClassifier
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignatureBuilder
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.schemas import OutcomeResult


def test_task_signature_prefers_explicit_public_metadata() -> None:
    signature = TaskSignatureClassifier.classify(
        {
            "category": "coding",
            "family": "dependency_recovery",
            "target_domain": "node_dependency",
            "allowed_tools": ["filesystem"],
            "failure_class": "DEPENDENCY_ERROR",
            "difficulty": "medium",
        }
    )
    assert signature.family == "dependency_recovery"
    assert signature.domain == "node_dependency"
    assert signature.uncertainty == 0.0
    assert signature.classification_source == "explicit_public_metadata"


def test_task_signature_abstains_when_heuristics_are_ambiguous() -> None:
    signature = TaskSignatureClassifier.classify({"objective": "Faça uma tarefa geral."})
    assert signature.family == "unknown"
    assert signature.uncertainty == 1.0
    assert signature.classification_source == "abstain"


def test_experience_signature_requires_explicit_verification() -> None:
    signature = ExperienceSignatureBuilder.build(
        {
            "metadata": {
                "family": "structured_validation",
                "category": "coding",
                "domain": "json_validation",
                "verified": True,
                "abstraction_level": 0.8,
            }
        },
        utility=0.25,
        sample_count=4,
    )
    assert signature.verified is True
    assert signature.historical_utility == 0.25
    assert signature.sample_count == 4


def test_signatures_persist_in_canonical_sqlite_schema(tmp_path) -> None:
    db = Database(tmp_path / "hermes.db")
    db.initialize()
    task_id = TaskSignatureClassifier.persist(
        db,
        TaskSignatureClassifier.classify({"category": "coding", "family": "configuration_repair", "target_domain": "service_configuration"}),
    )
    db.execute(
        "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES ('experience-1',NULL,'test','[]','ok',1,'[]','[]',1.0,'now')"
    )
    outcome = OutcomeResult(success=True, authority_level="private_mission_evaluator", evidence_refs=["signature-pass"], confidence=1.0, final=True)
    audit = VerifiedWritebackGate(db).evaluate(task_id=None, target_type="experience", target_id="experience-1", outcome_result=outcome)
    db.execute("UPDATE experiences SET verification_state='verified', verified_writeback_id=? WHERE id='experience-1'", (audit.audit_id,))
    experience_id = ExperienceSignatureBuilder.persist(
        db,
        ExperienceSignatureBuilder.build({"family": "configuration_repair", "verified": True}),
        "experience-1",
    )
    assert db.one("SELECT id FROM task_signatures WHERE id=?", (task_id,)) is not None
    assert db.one("SELECT id FROM experience_signatures WHERE id=?", (experience_id,)) is not None
