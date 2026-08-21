from __future__ import annotations

from ultron.cognition.task_signature import TaskSignature
from ultron.db import Database
from ultron.learning.experience_matcher import ExperienceMatcher
from ultron.learning.experience_router import ExperienceUtilityRouter, RoutingDecision
from ultron.learning.experience_signature import ExperienceSignature
from ultron.learning.experience_utility import ExperienceUtilityModel, UtilityEstimate


def _task() -> TaskSignature:
    return TaskSignature(category="coding", family="dependency_recovery", domain="node", required_tools=["filesystem"], uncertainty=0.0)


def _experience(utility: float = 0.4) -> ExperienceSignature:
    return ExperienceSignature(category="coding", family="dependency_recovery", domain="node", tool_families=["filesystem"], verified=True, historical_utility=utility, abstraction_level=0.7)


def test_matcher_uses_structured_family_signals() -> None:
    result = ExperienceMatcher().match(_task(), _experience())
    assert result.score > 0.8
    assert result.signals["family"] == 1.0


def test_router_abstains_without_paired_evidence() -> None:
    result = ExperienceUtilityRouter().decide(_task(), UtilityEstimate("e1", 0.9, 0.5, 0.0, 0.0, 0, 1.0))
    assert result.decision is RoutingDecision.ABSTAIN
    assert result.reason == "insufficient_paired_evidence"


def test_router_uses_only_positive_utility_with_evidence() -> None:
    result = ExperienceUtilityRouter().decide(_task(), UtilityEstimate("e1", 0.9, 0.3, 0.6, 0.162, 4, 0.4))
    assert result.decision is RoutingDecision.USE


def test_router_rejects_harmful_or_blocked_experience() -> None:
    estimate = UtilityEstimate("e1", 0.9, -0.3, 0.6, -0.162, 4, 0.4)
    assert ExperienceUtilityRouter().decide(_task(), estimate).decision is RoutingDecision.REJECT
    assert ExperienceUtilityRouter().decide(_task(), estimate, blocked=True).reason == "negative_transfer_firewall"


def test_utility_model_uses_paired_database_outcomes(tmp_path) -> None:
    db = Database(tmp_path / "router.db")
    db.initialize()
    db.execute("INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES ('e1',NULL,'test','[]','ok',1,'[]','[]',1.0,'now')")
    signature_id = "s1"
    db.execute("INSERT INTO task_signatures (id,task_id,category,family,domain,required_tools_json,uncertainty,source,created_at) VALUES ('s1',NULL,'coding','dependency_recovery','node','[]',0,'test','now')")
    ExperienceUtilityModel.record_pair_outcome(db, task_signature_id=signature_id, experience_id="e1", fresh_score=0.2, experienced_score=0.6)
    estimate = ExperienceUtilityModel.estimate(db, "e1", ExperienceMatcher().match(_task(), _experience()))
    assert estimate.sample_count == 1
    assert estimate.historical_mean_delta == 0.4
    assert estimate.expected_utility > 0
