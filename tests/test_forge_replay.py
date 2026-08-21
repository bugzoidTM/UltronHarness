from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from ultron.configuration import Settings, load_settings
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.research.forge_replay import ReplayCorpusBuilder, compare_learning

ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path: Path) -> Database:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    return db


def _experience(db: Database, experience_id: str, verified: bool) -> None:
    db.execute(
        "INSERT INTO experiences (id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (experience_id, "repair /tmp/example.py line 8", "[]", "resultado", 1, "[]", '["validar artefato"]', 0.9, datetime.now(UTC).isoformat()),
    )
    ExperienceSignatureBuilder.persist(
        db,
        ExperienceSignature(category="recovery", family="state_recovery", domain="test", verified=verified),
        experience_id,
    )


def test_replay_corpus_only_uses_verified_experience_and_generalizes_paths(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _experience(db, "verified", True)
    _experience(db, "unverified", False)
    builder = ReplayCorpusBuilder(db)
    corpus = builder.build()
    assert [item.experience_id for item in corpus] == ["verified"]
    assert "<caminho>" in corpus[0].problem_pattern
    assert builder.persist(corpus) == 1
    assert db.one("SELECT COUNT(*) AS count FROM distilled_procedures")["count"] == 1


def test_acg_requires_positive_mean_and_confidence_interval() -> None:
    positive = compare_learning([0.0, 0.0, 0.0], [1.0, 1.0, 1.0])
    assert positive.passed
    neutral = compare_learning([0.0, 1.0, 0.0], [0.0, 1.0, 0.0])
    assert not neutral.passed
