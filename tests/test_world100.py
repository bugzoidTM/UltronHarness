from __future__ import annotations

import json

import pytest

from ultron.research.world100 import run_world100_from_transfer


def test_world100_requires_observed_transfer_outcomes(tmp_path) -> None:
    with pytest.raises(ValueError, match="100 outcomes"):
        run_world100_from_transfer(tmp_path)


def test_world100_calibrates_from_persisted_traces(tmp_path) -> None:
    traces = [{"family": "validation", "success": index % 2 == 0} for index in range(50)]
    artifact = tmp_path / "run" / "transfer.json"
    artifact.parent.mkdir()
    artifact.write_text(json.dumps({"traces": {"fresh": traces, "experienced": traces}}), encoding="utf-8")
    metrics = run_world100_from_transfer(tmp_path)
    assert metrics.count == 100
    assert 0.0 <= metrics.brier <= 1.0
