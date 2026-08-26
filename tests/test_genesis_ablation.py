from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

from scripts.run_genesis_ablation import FROZEN_CP_01, FixtureAblationRunner, _fingerprint
from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner
from ultron.models.gateway import ModelResponse, Usage

ROOT = Path(__file__).resolve().parents[1]


class _FakeModel:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    async def generate(self, messages: list[dict[str, str]], *args: object, **kwargs: object) -> ModelResponse:
        del args, kwargs
        self.messages.append(messages)
        return ModelResponse("11", [], Usage(), 1, "fake-model", "stop", True)


def test_real_runner_uses_integer_projection_codes_and_no_answer_frame(tmp_path: Path) -> None:
    raw = deepcopy(load_settings(ROOT).raw)
    settings = Settings(raw=raw, root_dir=tmp_path)
    runner = GenesisPublicRunner(settings)
    fake_model = _FakeModel()
    runner.models = fake_model
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")

    baseline = asyncio.run(runner.run_one(task=task, condition="baseline", run_id="test-a", model_name="fake", seed=42, max_tokens=1024, frame_projection="none"))
    intermediate = asyncio.run(runner.run_one(task=task, condition="program_no_answer", run_id="test-b", model_name="fake", seed=42, max_tokens=1024, program=FROZEN_CP_01, frame_projection="intermediate"))
    full = asyncio.run(runner.run_one(task=task, condition="program", run_id="test-c", model_name="fake", seed=42, max_tokens=1024, program=FROZEN_CP_01, frame_projection="full"))

    assert baseline.execution.context_metrics["frame_projection"] == 0
    assert intermediate.execution.context_metrics["frame_projection"] == 1
    assert full.execution.context_metrics["frame_projection"] == 2
    intermediate_prompt = json.dumps(fake_model.messages[1], ensure_ascii=False)
    assert "candidate_answer" not in intermediate_prompt
    assert "verification" not in intermediate_prompt
    assert "trace" not in intermediate_prompt
    assert "rationale" not in intermediate_prompt
    full_prompt = json.dumps(fake_model.messages[2], ensure_ascii=False)
    assert "candidate_answer" in full_prompt
    assert "verification" in full_prompt


def test_no_answer_projection_excludes_candidate_answer_and_verification() -> None:
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")
    intermediate = {"facts": ["problem represented"], "unknowns": ["candidate answer"], "constraints": ["explicit relation"], "hypotheses": ["arithmetic"], "predictions": ["answer will satisfy verifier"]}
    messages = GenesisPublicRunner._messages(task, "program_no_answer", intermediate)
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "candidate_answer" not in serialized
    assert "verification" not in serialized
    assert "facts" in serialized
    assert "hypotheses" in serialized


def test_ablation_fixture_is_causal_and_has_no_writeback() -> None:
    runner = FixtureAblationRunner()
    task_map = {task.id: task for task in runner.load_tasks()}
    rows: dict[str, list[object]] = {"A": [], "B": [], "C": []}
    for label, condition, projection in (("A", "baseline", "none"), ("B", "program_no_answer", "intermediate"), ("C", "program", "full")):
        for task_id in ("reasoning_06", "reasoning_07"):
            result = asyncio.run(runner.run_one(task=task_map[task_id], condition=condition, run_id="test", model_name="same-model", seed=42, max_tokens=1024, program=None if label == "A" else FROZEN_CP_01, frame_projection=projection))
            rows[label].append(result)
    scores = {label: sum(result.evaluation.score for result in results) / 2 for label, results in rows.items()}
    assert scores == {"A": 0.5, "B": 0.5, "C": 1.0}
    all_results = [result for results in rows.values() for result in results]
    assert {result.manifest.model for result in all_results} == {"same-model"}
    assert {result.manifest.seed for result in all_results} == {42}
    assert {_fingerprint(result.task) for result in rows["A"]} == {_fingerprint(result.task) for result in rows["B"]} == {_fingerprint(result.task) for result in rows["C"]}
    assert runner.persist_result(rows["C"][0]) is None


def test_ablation_uses_frozen_program_without_synthesis_or_writeback() -> None:
    source = (ROOT / "scripts" / "run_genesis_ablation.py").read_text(encoding="utf-8")
    assert "synthesis_performed" in source
    assert "writeback_performed" in source
    assert "GenesisController" not in source
    assert FROZEN_CP_01.operators == ["REPRESENT", "DECOMPOSE", "HYPOTHESIZE", "DEDUCT"]
