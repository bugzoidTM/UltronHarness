from __future__ import annotations

from pathlib import Path

from ultron.cognition.critic import Evidence, EvidenceCritic
from ultron.cognition.world_model import WorldModel
from ultron.db import Database


def test_world_model_predicts_and_observes_in_shadow_without_blocking(tmp_path: Path) -> None:
    db = Database(tmp_path / "world.db")
    model = WorldModel(db)
    first = model.predict("run_tests", {"suite": "unit"})
    assert first.shadow is True
    assert first.predicted_success == 0.5
    model.observe(first, True, "all tests passed")
    second = model.predict("run_tests")
    assert second.predicted_success == 0.666667
    model.observe(second, False, "timeout")
    metrics = model.metrics()
    assert metrics.observations == 2
    assert 0.0 <= metrics.prediction_accuracy <= 1.0
    assert 0.0 <= metrics.brier_score <= 1.0
    assert db.one("SELECT COUNT(*) AS count FROM world_model_observations") == {"count": 2}


def test_evidence_critic_prefers_deterministic_proof(tmp_path: Path) -> None:
    critic = EvidenceCritic()
    accepted = critic.assess([Evidence("exit_code", 0, "runner"), Evidence("test_passed", True, "pytest")])
    assert accepted.accepted is True
    assert accepted.confidence == 1.0
    assert accepted.needs_llm_critic is False
    rejected = critic.assess([Evidence("schema_valid", False, "validator")])
    assert rejected.accepted is False
    fallback = critic.assess([Evidence("narrative", "parece funcionar", "agent")])
    assert fallback.accepted is None
    assert fallback.needs_llm_critic is True
    evidence = critic.file_exists(tmp_path / "missing.txt")
    assert evidence.value is False
