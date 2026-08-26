from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from scripts.run_genesis_v1 import DIAGNOSIS_IDS, HOLDOUT_IDS, MAX_DECISIONS, TOTAL_BUDGET
from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner
from ultron.genesis.schemas import (
    CognitivePolicy,
    CognitivePolicyRule,
    DeductionOutput,
    FinalAnswerOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)
from ultron.genesis.vm import AdaptiveCognitiveVM, GenericClosedLoopVM

ROOT = Path(__file__).resolve().parents[1]


class _FeedbackGateway:
    def __init__(self, verification_statuses: list[str] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.verification_statuses = list(verification_statuses or ["supported"])
        self.deduction_index = 0
        self.verification_index = 0

    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        self.calls.append({"schema": schema.__name__, "messages": messages, "model": model_name, **kwargs})
        if schema is RepresentationOutput:
            return RepresentationOutput(entities=["numbers"], facts=["explicit relation"], constraints=["derive answer"], unknowns=["next value"])
        if schema is HypothesisOutput:
            return HypothesisOutput(hypotheses=["test the relation"], predictions=["a justified conclusion exists"])
        if schema is DeductionOutput:
            self.deduction_index += 1
            return DeductionOutput(conclusion="wrong" if self.deduction_index == 1 and len(self.verification_statuses) > 1 else "11")
        if schema is VerificationOutput:
            status = self.verification_statuses[min(self.verification_index, len(self.verification_statuses) - 1)]
            self.verification_index += 1
            return VerificationOutput(status=status, explanation=f"feedback={status}")
        if schema is FinalAnswerOutput:
            return FinalAnswerOutput(answer="11")
        raise AssertionError(f"unexpected_schema:{schema}")


def _policy(max_decisions: int = MAX_DECISIONS) -> CognitivePolicy:
    return CognitivePolicy(
        id="CP-ADAPTIVE",
        rules=[
            CognitivePolicyRule(conditions=["no_representation"], operator="REPRESENT", priority=0),
            CognitivePolicyRule(conditions=["no_hypothesis"], operator="HYPOTHESIZE", priority=1),
            CognitivePolicyRule(conditions=["no_candidate"], operator="DEDUCT", priority=2),
            CognitivePolicyRule(conditions=["verification_contradicted"], operator="DEDUCT", priority=3),
            CognitivePolicyRule(conditions=["verification_uncertain"], operator="DEDUCT", priority=4),
            CognitivePolicyRule(conditions=["has_candidate"], operator="VERIFY", priority=5),
        ],
        max_decisions=max_decisions,
        rationale="Política de teste adaptativa; rationale é metadado.",
    )


def test_v1_protocol_constants_are_frozen() -> None:
    assert DIAGNOSIS_IDS == ("reasoning_01", "reasoning_02")
    assert HOLDOUT_IDS == ("reasoning_06", "reasoning_07")
    assert TOTAL_BUDGET == 1024
    assert MAX_DECISIONS == 6


def test_adaptive_policy_reacts_to_contradicted_feedback_within_budget() -> None:
    gateway = _FeedbackGateway(["contradicted", "supported"])
    result = asyncio.run(
        AdaptiveCognitiveVM(gateway, model_name="fake", seed=42, max_tokens=170, max_steps=6).execute_policy(
            "Calcule 24 dividido por 6 e some 7.", _policy()
        )
    )
    assert result.valid is True
    assert result.termination_reason == "verification_supported"
    assert result.decisions == 6
    assert result.model_calls == 6
    assert [entry["operator"] for entry in result.frame.trace] == ["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY", "DEDUCT", "VERIFY"]
    assert "verification_contradicted" in result.frame.trace[4]["conditions"]
    assert result.frame.verification["status"] == "supported"


def test_adaptive_policy_fails_closed_when_no_rule_matches_new_state() -> None:
    gateway = _FeedbackGateway(["supported"])
    policy = CognitivePolicy(
        id="CP-FAIL-CLOSED",
        rules=[
            CognitivePolicyRule(conditions=["no_representation"], operator="REPRESENT", priority=0),
            CognitivePolicyRule(conditions=["no_hypothesis", "verification_supported"], operator="HYPOTHESIZE", priority=1),
            CognitivePolicyRule(conditions=["no_candidate", "verification_supported"], operator="DEDUCT", priority=2),
            CognitivePolicyRule(conditions=["has_candidate", "has_facts"], operator="VERIFY", priority=3),
            CognitivePolicyRule(conditions=["verification_contradicted", "has_facts"], operator="DEDUCT", priority=4),
            CognitivePolicyRule(conditions=["verification_uncertain", "has_facts"], operator="DEDUCT", priority=5),
        ],
        max_decisions=MAX_DECISIONS,
        rationale="Política deliberadamente incompleta para testar rejeição segura.",
    )
    result = asyncio.run(
        AdaptiveCognitiveVM(gateway, model_name="fake", seed=42, max_tokens=170, max_steps=6).execute_policy(
            "Calcule 24 dividido por 6 e some 7.", policy
        )
    )
    assert result.valid is False
    assert result.error == "policy_no_matching_rule"
    assert result.termination_reason == "no_matching_rule"


def test_generic_closed_loop_is_accumulative_and_uses_same_four_primitives() -> None:
    gateway = _FeedbackGateway(["supported"])
    result = asyncio.run(
        GenericClosedLoopVM(gateway, model_name="fake", seed=42, max_tokens=170, max_steps=6).execute_closed_loop(
            "Calcule 24 dividido por 6 e some 7.", max_decisions=6
        )
    )
    assert result.valid is True
    assert result.decisions == 4
    assert result.model_calls == 4
    assert [entry["operator"] for entry in result.frame.trace] == ["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"]
    assert all("Frame atual" in call["messages"][1]["content"] for call in gateway.calls)


def test_runner_parity_uses_same_total_budget_for_direct_and_closed_loop(tmp_path: Path) -> None:
    raw = deepcopy(load_settings(ROOT).raw)
    settings = Settings(raw=raw, root_dir=tmp_path)
    runner = GenesisPublicRunner(settings)
    runner.models = _FeedbackGateway(["supported"])
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")
    policy = _policy()
    direct = asyncio.run(runner.run_one(task=task, condition="direct", run_id="a", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, decision_budget=1))
    generic = asyncio.run(runner.run_one(task=task, condition="generic_closed_loop", run_id="b", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, decision_budget=MAX_DECISIONS))
    adaptive = asyncio.run(runner.run_one(task=task, condition="adaptive_policy", run_id="c", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, policy=policy, decision_budget=MAX_DECISIONS))

    assert direct.execution.context_metrics["decision_budget"] == 1
    assert direct.execution.context_metrics["call_tokens"] == 1024
    assert generic.execution.context_metrics["decision_budget"] == 6
    assert generic.execution.context_metrics["call_tokens"] == 170
    assert adaptive.execution.context_metrics["decision_budget"] == 6
    assert adaptive.execution.context_metrics["call_tokens"] == 170
    assert {direct.manifest.config_hash, generic.manifest.config_hash, adaptive.manifest.config_hash}.__len__() == 1


def test_policy_source_has_no_external_execution_path() -> None:
    source = (ROOT / "ultron" / "genesis" / "vm.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "httpx", "socket", "DECOMPOSE", "BACKTRACK"):
        assert forbidden not in source
