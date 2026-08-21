from __future__ import annotations

from pathlib import Path

from ultron.db import Database
from ultron.memory.governor import MemoryGovernor
from ultron.research.learn2 import VerifiedExperiencePool


def test_learn2_pool_admits_only_verified_procedures_and_selects_requested_count(tmp_path: Path) -> None:
    db = Database(tmp_path / "learn2.db")
    db.initialize()
    pool = VerifiedExperiencePool(MemoryGovernor(db))
    assert pool.admitted_count == 200
    selected = pool.select(25)
    assert len(selected) == 25
    assert all(item.startswith("[") and "Procedimento verificado:" in item for item in selected)
    assert {"reasoning", "coding", "tool_use", "recovery"} <= {
        item.split("]", 1)[0].removeprefix("[") for item in selected
    }
    assert db.one("SELECT COUNT(*) AS count FROM memory_write_decisions") == {"count": 200}


def test_learn2_pool_handles_zero_and_rejects_unavailable_size(tmp_path: Path) -> None:
    db = Database(tmp_path / "learn2.db")
    db.initialize()
    pool = VerifiedExperiencePool(MemoryGovernor(db))
    assert pool.select(0) == []
    try:
        pool.select(201)
    except ValueError:
        pass
    else:
        raise AssertionError("O pool não pode selecionar experiências que não foram verificadas")
