from __future__ import annotations

from ultron.db import Database
from ultron.learning.distillation import ExperienceDistiller, ProcedureEvidence
from ultron.learning.skill_routing import FamilySkillRouter, SkillFamilyState


def _evidence(utility: float = 0.2) -> ProcedureEvidence:
    return ProcedureEvidence(
        experience_id=f"e-{utility}",
        family="structured_validation",
        principle="validar estrutura antes de modificar",
        preconditions=("parser disponível",),
        recommended_actions=("parse", "validate"),
        avoid_actions=("mutate_before_validate",),
        success=True,
        utility=utility,
        verified=True,
    )


def test_distillation_requires_three_compatible_verified_sources() -> None:
    assert ExperienceDistiller.distill([_evidence(), _evidence()]) is None
    procedure = ExperienceDistiller.distill([_evidence(0.1), _evidence(0.2), _evidence(0.3)])
    assert procedure is not None
    assert procedure.evidence_count == 3
    assert procedure.recommended_actions == ("parse", "validate")
    assert len(procedure.source_experience_ids) == 3


def test_distillation_refuses_nonpositive_or_mixed_provenance() -> None:
    assert ExperienceDistiller.distill([_evidence(-0.1), _evidence(-0.2), _evidence(-0.3)]) is None
    mixed = [_evidence(), ProcedureEvidence("other", "planning", "outro", (), ("plan",), (), True, 0.2, True), _evidence()]
    assert ExperienceDistiller.distill(mixed) is None


def test_family_skill_router_does_not_activate_globally(tmp_path) -> None:
    candidate = FamilySkillRouter.classify("s1", "structured_validation", [0.2, 0.3, 0.25])
    blocked = FamilySkillRouter.classify("s1", "planning", [-0.1, -0.2, -0.15])
    assert candidate.state is SkillFamilyState.ACTIVE_CANDIDATE
    assert blocked.state is SkillFamilyState.BLOCKED
    db = Database(tmp_path / "skills.db")
    db.initialize()
    db.execute("INSERT INTO skills (id,name,description,created_at,updated_at) VALUES ('s1','validate','test','now','now')")
    FamilySkillRouter.persist(db, candidate)
    FamilySkillRouter.persist(db, blocked)
    assert FamilySkillRouter.can_use(db, "s1", "structured_validation") is True
    assert FamilySkillRouter.can_use(db, "s1", "planning") is False
