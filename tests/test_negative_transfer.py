from __future__ import annotations

from ultron.db import Database
from ultron.learning.negative_transfer import FamilyUtilityState, NegativeTransferFirewall
from ultron.learning.pairwise_utility import RetrievalOutcome, evaluate_pair, summarize_retrieval


def test_pairwise_classifies_helpful_neutral_and_harmful_retrievals() -> None:
    helpful = evaluate_pair(0.2, 0.5)
    neutral = evaluate_pair(0.2, 0.205)
    harmful = evaluate_pair(0.5, 0.2)
    assert helpful.outcome is RetrievalOutcome.HELPFUL
    assert neutral.outcome is RetrievalOutcome.NEUTRAL
    assert harmful.outcome is RetrievalOutcome.HARMFUL
    summary = summarize_retrieval([helpful, neutral, harmful])
    assert summary.helpful_rate == summary.neutral_rate == summary.harmful_rate == round(1 / 3, 6)


def test_firewall_classifies_harmful_and_promotable_families() -> None:
    harmful = NegativeTransferFirewall.classify("planning", "generic_procedural", [-0.20, -0.15, -0.10])
    promotable = NegativeTransferFirewall.classify("dependency_recovery", "dependency_recovery", [0.25, 0.30, 0.35])
    assert harmful.state is FamilyUtilityState.HARMFUL
    assert promotable.state is FamilyUtilityState.PROMOTABLE


def test_firewall_persists_and_blocks_harmful_family_pair(tmp_path) -> None:
    db = Database(tmp_path / "firewall.db")
    db.initialize()
    db.execute("INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES ('e1',NULL,'test','[]','ok',1,'[]','[]',1.0,'now')")
    db.execute("INSERT INTO task_signatures (id,task_id,category,family,domain,required_tools_json,uncertainty,source,created_at) VALUES ('s1',NULL,'reasoning','planning','local','[]',0,'test','now')")
    db.execute("INSERT INTO experience_signatures (id,experience_id,category,family,domain,failure_classes_json,tool_families_json,abstraction_level,verified,historical_utility,sample_count,source,created_at,updated_at) VALUES ('es1','e1','reasoning','generic_procedural','local','[]','[]',0.5,1,0,3,'test','now','now')")
    for index, delta in enumerate((-0.1, -0.2, -0.15)):
        db.execute("INSERT INTO experience_pair_utility (id,run_id,task_signature_id,experience_id,fresh_score,experienced_score,paired_delta,created_at) VALUES (?,?,?,?,?,?,?,?)", (f'p{index}', None, 's1', 'e1', 0.5, 0.5 + delta, delta, 'now'))
    utility = NegativeTransferFirewall.recalculate(db, "planning", "generic_procedural")
    assert utility.state is FamilyUtilityState.HARMFUL
    assert NegativeTransferFirewall.is_blocked(db, "planning", "generic_procedural") is True
