from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from scripts.run_genesis_v022 import CALL_BUDGET, DIAGNOSIS_IDS, HOLDOUT_IDS, TOTAL_BUDGET
from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner
from ultron.genesis.schemas import (
    CognitiveProgram,
    DeductionOutput,
    DeliberationOutput,
    FinalAnswerOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)

ROOT = Path(__file__).resolve().parents[1]


class _StructuredGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        self.calls.append({"schema": schema.__name__, "messages": messages, "model": model_name, **kwargs})
        if schema is RepresentationOutput:
            return RepresentationOutput(entities=["numbers"], facts=["explicit relation"], constraints=["derive answer"], unknowns=["next value"])
        if schema is HypothesisOutput:
            return HypothesisOutput(hypotheses=["test the relation"], predictions=["a justified conclusion exists"])
        if schema is DeductionOutput:
            return DeductionOutput(conclusion="11")
        if schema is VerificationOutput:
            return VerificationOutput(status="supported", explanation="consistent with the available frame")
        if schema is FinalAnswerOutput:
            return FinalAnswerOutput(answer="11")
        if schema is DeliberationOutput:
            return DeliberationOutput(note="continue checking the objective", candidate_answer="11")
        raise AssertionError(f"unexpected schema: {schema}")


class _FakeRunnerGateway:
    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        del messages, model_name, kwargs
        if schema is RepresentationOutput:
            return RepresentationOutput(facts=["fact"], constraints=["constraint"], unknowns=["unknown"])
        if schema is HypothesisOutput:
            return HypothesisOutput(hypotheses=["hypothesis"], predictions=["prediction"])
        if schema is DeductionOutput:
            return DeductionOutput(conclusion="11")
        if schema is VerificationOutput:
            return VerificationOutput(status="supported", explanation="supported")
        if schema is FinalAnswerOutput:
            return FinalAnswerOutput(answer="11")
        if schema is DeliberationOutput:
            return DeliberationOutput(note="note", candidate_answer="11")
        raise AssertionError(f"unexpected schema: {schema}")


class _GatewayModel:
    def __init__(self) -> None:
        self.gateway = _FakeRunnerGateway()

    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        return await self.gateway.structured(schema, messages, model_name, **kwargs)


def test_v022_protocol_constants_are_frozen() -> None:
    assert DIAGNOSIS_IDS == ("reasoning_01", "reasoning_02")
    assert HOLDOUT_IDS == ("reasoning_06", "reasoning_07")
    assert TOTAL_BUDGET == 1024
    assert CALL_BUDGET == 4


def test_public_runner_keeps_total_budget_and_call_parity(tmp_path: Path) -> None:
    raw = deepcopy(load_settings(ROOT).raw)
    settings = Settings(raw=raw, root_dir=tmp_path)
    runner = GenesisPublicRunner(settings)
    runner.models = _GatewayModel()
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")
    program = CognitiveProgram(id="CP-TEST", operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"], rationale="Programa de teste estruturado.")

    direct = asyncio.run(runner.run_one(task=task, condition="direct", run_id="a", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, call_budget=1))
    matched = asyncio.run(runner.run_one(task=task, condition="matched_compute", run_id="b", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, call_budget=CALL_BUDGET))
    program_result = asyncio.run(runner.run_one(task=task, condition="program", run_id="c", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, program=program, call_budget=CALL_BUDGET))

    assert direct.execution.context_metrics["call_budget"] == 1
    assert direct.execution.context_metrics["call_tokens"] == 1024
    assert direct.execution.context_metrics["model_calls"] == 1
    assert matched.execution.context_metrics["call_budget"] == 4
    assert matched.execution.context_metrics["call_tokens"] == 256
    assert matched.execution.context_metrics["model_calls"] == 4
    assert program_result.execution.context_metrics["call_budget"] == 4
    assert program_result.execution.context_metrics["call_tokens"] == 256
    assert program_result.execution.context_metrics["model_calls"] == 4
    assert program_result.vm_execution is not None and program_result.vm_execution.valid
    assert {direct.manifest.config_hash, matched.manifest.config_hash, program_result.manifest.config_hash}.__len__() == 1


def test_structured_operator_sequence_has_no_domain_solver() -> None:
    from ultron.genesis.vm import CognitiveVM

    source = (ROOT / "ultron" / "genesis" / "vm.py").read_text(encoding="utf-8")
    assert "import re" not in source
    assert "multiplicado" not in source
    assert "sequência" not in source
    gateway = _StructuredGateway()
    program = CognitiveProgram(id="CP-TEST", operators=["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"], rationale="Semântica de controle.")
    result = asyncio.run(CognitiveVM(gateway, model_name="fake", seed=42, max_tokens=256, max_steps=4).execute("Calcule 24 dividido por 6 e some 7.", program))

    assert result.valid is True
    assert result.steps == 4
    assert result.model_calls == 4
    assert result.frame.candidate_answer == "11"
    assert result.frame.verification["status"] == "supported"
    assert [call["schema"] for call in gateway.calls] == ["RepresentationOutput", "HypothesisOutput", "DeductionOutput", "VerificationOutput"]
    assert {call["model"] for call in gateway.calls} == {"fake"}
    assert {call["seed"] for call in gateway.calls} == {42}
    assert {call["max_tokens"] for call in gateway.calls} == {256}


def test_program_schema_exposes_only_four_non_solving_operators() -> None:
    import pytest

    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["DECOMPOSE"], rationale="Operador removido.")
    with pytest.raises(ValueError):
        CognitiveProgram(id="CP-BAD", operators=["BACKTRACK"], rationale="Operador removido.")
