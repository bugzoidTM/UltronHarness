from __future__ import annotations

from ultron.cognition.task_signature import TaskSignature
from ultron.db import Database
from ultron.learning.experience_router import RoutingDecision
from ultron.learning.experience_signature import ExperienceSignature
from ultron.learning.routing_service import ShadowExperienceRoutingService


def test_shadow_routing_persists_abstention_without_production_effect(tmp_path) -> None:
    db = Database(tmp_path / "routing.db")
    db.initialize()
    db.execute("INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES ('e1',NULL,'test','[]','ok',1,'[]','[]',1.0,'now')")
    service = ShadowExperienceRoutingService(db)
    result = service.evaluate(
        TaskSignature(category="coding", family="dependency_recovery", domain="node", uncertainty=0.0),
        "e1",
        ExperienceSignature(category="coding", family="dependency_recovery", domain="node", verified=True),
    )
    row = db.one("SELECT decision,reason,metadata_json FROM routing_decisions")
    assert result.decision is RoutingDecision.ABSTAIN
    assert row is not None
    assert row["decision"] == "ABSTAIN"
    assert '"shadow":true' in row["metadata_json"]
