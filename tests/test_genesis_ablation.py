from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.audit_genesis_v2final import _load_public_tasks, audit_payload, render_markdown
from scripts.run_genesis_v1 import DIAGNOSIS_IDS, HOLDOUT_IDS, MAX_DECISIONS, TOTAL_BUDGET
from scripts.run_genesis_v2final import CALL_TOKENS as V2FINAL_CALL_TOKENS
from scripts.run_genesis_v2final import HOLDOUT_IDS as V2FINAL_HOLDOUT_IDS
from scripts.run_genesis_v2final import MAX_DECISIONS as V2FINAL_MAX_DECISIONS
from scripts.run_genesis_v2final import TOTAL_BUDGET as V2FINAL_TOTAL_BUDGET
from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner
from ultron.genesis.schemas import (
    GENESIS_V2_PROTOCOL_VERSION,
    GENESIS_V2FINAL_PROTOCOL_VERSION,
    GENESIS_V2R_PROTOCOL_VERSION,
    CognitivePolicy,
    CognitivePolicyRule,
    DeductionOutput,
    FinalAnswerOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)
from ultron.genesis.vm import AdaptiveCognitiveVM, EndogenousExecutiveVM, GenericClosedLoopVM

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
            return RepresentationOutput(entities=["numbers"], facts=["explicit relation"], constraints=["derive answer"], unknowns=["next value"], next_operator="HYPOTHESIZE")
        if schema is HypothesisOutput:
            return HypothesisOutput(hypotheses=["test the relation"], predictions=["a justified conclusion exists"], next_operator="DEDUCT")
        if schema is DeductionOutput:
            self.deduction_index += 1
            return DeductionOutput(conclusion="wrong" if self.deduction_index == 1 and len(self.verification_statuses) > 1 else "11", next_operator="VERIFY")
        if schema is VerificationOutput:
            status = self.verification_statuses[min(self.verification_index, len(self.verification_statuses) - 1)]
            self.verification_index += 1
            next_operator = "DEDUCT" if status in {"contradicted", "uncertain"} else "VERIFY"
            return VerificationOutput(status=status, explanation=f"feedback={status}", next_operator=next_operator)
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


def test_endogenous_executive_uses_next_operator_without_router_call() -> None:
    gateway = _FeedbackGateway(["supported"])
    result = asyncio.run(
        EndogenousExecutiveVM(gateway, model_name="fake", seed=42, max_tokens=170, max_steps=6).execute_online(
            "Calcule 24 dividido por 6 e some 7.", max_decisions=6
        )
    )
    assert result.valid is True
    assert result.termination_reason == "verification_supported"
    assert result.decisions == 4
    assert result.model_calls == 4
    assert [entry["operator"] for entry in result.frame.trace] == ["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY"]
    assert [entry["next_operator"] for entry in result.frame.trace] == ["HYPOTHESIZE", "DEDUCT", "VERIFY", "VERIFY"]
    assert len(gateway.calls) == result.model_calls


def test_endogenous_executive_recovers_from_contradicted_feedback() -> None:
    gateway = _FeedbackGateway(["contradicted", "supported"])
    result = asyncio.run(
        EndogenousExecutiveVM(gateway, model_name="fake", seed=42, max_tokens=170, max_steps=6).execute_online(
            "Calcule 24 dividido por 6 e some 7.", max_decisions=6
        )
    )
    assert result.valid is True
    assert result.termination_reason == "verification_supported"
    assert result.decisions == 6
    assert [entry["operator"] for entry in result.frame.trace] == ["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY", "DEDUCT", "VERIFY"]
    assert any(entry["verification_status"] == "contradicted" for entry in result.frame.trace)


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
    endogenous = asyncio.run(runner.run_one(task=task, condition="endogenous_executive", run_id="d", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, decision_budget=MAX_DECISIONS))
    v2r = asyncio.run(runner.run_one(task=task, condition="endogenous_executive_v2r", run_id="e", model_name="fake", seed=42, max_tokens=TOTAL_BUDGET, decision_budget=4))
    v2final_fixed = asyncio.run(runner.run_one(task=task, condition="generic_closed_loop_v2final", run_id="f", model_name="fake", seed=42, max_tokens=V2FINAL_TOTAL_BUDGET, decision_budget=V2FINAL_MAX_DECISIONS))
    v2final_endogenous = asyncio.run(runner.run_one(task=task, condition="endogenous_executive_v2final", run_id="g", model_name="fake", seed=42, max_tokens=V2FINAL_TOTAL_BUDGET, decision_budget=V2FINAL_MAX_DECISIONS))

    assert direct.execution.context_metrics["decision_budget"] == 1
    assert direct.execution.context_metrics["call_tokens"] == 1024
    assert generic.execution.context_metrics["decision_budget"] == 6
    assert generic.execution.context_metrics["call_tokens"] == 170
    assert adaptive.execution.context_metrics["decision_budget"] == 6
    assert adaptive.execution.context_metrics["call_tokens"] == 170
    assert endogenous.execution.context_metrics["decision_budget"] == 6
    assert endogenous.execution.context_metrics["call_tokens"] == 170
    assert endogenous.manifest.benchmark_version == GENESIS_V2_PROTOCOL_VERSION
    assert v2r.execution.context_metrics["decision_budget"] == 4
    assert v2r.execution.context_metrics["call_tokens"] == 256
    assert v2r.manifest.benchmark_version == GENESIS_V2R_PROTOCOL_VERSION
    assert v2final_fixed.execution.context_metrics["decision_budget"] == V2FINAL_MAX_DECISIONS
    assert v2final_endogenous.execution.context_metrics["decision_budget"] == V2FINAL_MAX_DECISIONS
    assert v2final_fixed.execution.context_metrics["call_tokens"] == V2FINAL_CALL_TOKENS
    assert v2final_endogenous.execution.context_metrics["call_tokens"] == V2FINAL_CALL_TOKENS
    assert v2final_fixed.manifest.benchmark_version == GENESIS_V2FINAL_PROTOCOL_VERSION
    assert v2final_endogenous.manifest.benchmark_version == GENESIS_V2FINAL_PROTOCOL_VERSION
    assert v2final_fixed.manifest.config_hash == v2final_endogenous.manifest.config_hash
    assert v2final_fixed.manifest.config_hash != direct.manifest.config_hash
    assert {direct.manifest.config_hash, generic.manifest.config_hash, adaptive.manifest.config_hash, endogenous.manifest.config_hash, v2r.manifest.config_hash}.__len__() == 1


def test_v2final_protocol_contract_is_frozen() -> None:
    assert V2FINAL_HOLDOUT_IDS == ("reasoning_06", "reasoning_07")
    assert V2FINAL_TOTAL_BUDGET == 1792
    assert V2FINAL_MAX_DECISIONS == 7
    assert V2FINAL_CALL_TOKENS == 256


def test_v2final_rejects_non_seven_decision_budget(tmp_path: Path) -> None:
    raw = deepcopy(load_settings(ROOT).raw)
    settings = Settings(raw=raw, root_dir=tmp_path)
    runner = GenesisPublicRunner(settings)
    task = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")
    with pytest.raises(ValueError, match="v2final_decision_budget_must_be_seven"):
        asyncio.run(runner.run_one(task=task, condition="generic_closed_loop_v2final", run_id="invalid-final", model_name="fake", seed=42, max_tokens=V2FINAL_TOTAL_BUDGET, decision_budget=4))


def test_v2r_structured_outputs_are_compact() -> None:
    with pytest.raises(ValueError):
        RepresentationOutput(entities=["x"] * 5, next_operator="HYPOTHESIZE")
    with pytest.raises(ValueError):
        HypothesisOutput(hypotheses=["x"] * 3, next_operator="DEDUCT")
    with pytest.raises(ValueError):
        VerificationOutput(status="uncertain", explanation="x" * 97, next_operator="DEDUCT")


def test_policy_source_has_no_external_execution_path() -> None:
    source = (ROOT / "ultron" / "genesis" / "vm.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "httpx", "socket", "DECOMPOSE", "BACKTRACK"):
        assert forbidden not in source



def _audit_row(
    condition: str,
    task_id: str,
    *,
    candidate_answer: str | None = None,
    final_verification_status: str = "uncertain",
    termination_reason: str = "decision_budget_exceeded",
    recovered: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {
        "task_id": task_id,
        "condition": condition,
        "model": "qwen2.5:3b",
        "seed": 42,
        "config_hash": "paired-config",
        "decision_budget": 7,
        "call_tokens": 256,
        "model_calls": 7,
        "decisions": 7,
        "vm_valid": False,
        "failure_category": "VM_ERROR",
        "termination_reason": termination_reason,
        "recovery_attempted": condition == "endogenous_executive_v2final",
        "recovered": recovered,
        "trace": [{"operator": "VERIFY", "verification_status": final_verification_status}],
    }
    if candidate_answer is not None:
        row["candidate_answer"] = candidate_answer
    return row


def _audit_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "protocol": "genesis-v2-final-executive-control",
        "holdout_task_ids": ["reasoning_06", "reasoning_07"],
        "diagnosis_task_ids": [],
        "max_decisions_per_task": 7,
        "total_token_budget_per_task_BC": 1792,
        "call_tokens_fixed_and_endogenous": 256,
        "holdout_sent_to_synthesizer": False,
        "rationale_used_for_execution": False,
        "synthesis_performed": False,
        "writeback_performed": False,
        "rows": rows,
    }


def test_v2final_offline_audit_does_not_infer_candidate_from_candidate_present() -> None:
    rows = [
        _audit_row(condition, task_id)
        for condition in ("generic_closed_loop_v2final", "endogenous_executive_v2final")
        for task_id in ("reasoning_06", "reasoning_07")
    ]
    for row in rows:
        row["trace"] = [{"operator": "DEDUCT", "state": "candidate_present=True;verification_status=uncertain"}]
    audit = audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))
    assert audit["decision"] == "AUDIT_INCONCLUSIVE_MISSING_CANDIDATE_ANSWER"
    assert audit["new_model_calls"] == 0
    assert audit["metrics"]["B_fixed_executive"]["external_accuracy"] is None
    assert audit["metrics"]["C_endogenous_executive"]["external_accuracy"] is None
    assert audit["metrics"]["ecg_task_C_minus_B"] is None
    assert audit["metrics"]["ecg_self_C_minus_B"] == 0.0
    assert all(row["candidate_available"] is False for row in audit["rows"])


def test_v2final_offline_audit_scores_explicit_candidates_even_after_budget_error() -> None:
    rows = [
        _audit_row("generic_closed_loop_v2final", "reasoning_06", candidate_answer="11"),
        _audit_row("generic_closed_loop_v2final", "reasoning_07", candidate_answer="54"),
        _audit_row("endogenous_executive_v2final", "reasoning_06", candidate_answer="11"),
        _audit_row("endogenous_executive_v2final", "reasoning_07", candidate_answer="162"),
    ]
    audit = audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))
    assert audit["decision"] == "AUDIT_COMPLETE"
    assert audit["metrics"]["B_fixed_executive"]["external_accuracy"] == 0.5
    assert audit["metrics"]["C_endogenous_executive"]["external_accuracy"] == 1.0
    assert audit["metrics"]["ecg_task_C_minus_B"] == 0.5
    assert audit["metrics"]["ecg_self_C_minus_B"] == 0.0
    assert all(row["candidate_source"] == "row.candidate_answer" for row in audit["rows"])


def test_v2final_offline_audit_separates_self_termination_from_task_score() -> None:
    rows = [
        _audit_row("generic_closed_loop_v2final", "reasoning_06", candidate_answer="11"),
        _audit_row("generic_closed_loop_v2final", "reasoning_07", candidate_answer="162"),
        _audit_row("endogenous_executive_v2final", "reasoning_06", candidate_answer="11", final_verification_status="supported", termination_reason="verification_supported"),
        _audit_row("endogenous_executive_v2final", "reasoning_07", candidate_answer="162"),
    ]
    audit = audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))
    assert audit["metrics"]["B_fixed_executive"]["external_accuracy"] == 1.0
    assert audit["metrics"]["C_endogenous_executive"]["external_accuracy"] == 1.0
    assert audit["metrics"]["ecg_task_C_minus_B"] == 0.0
    assert audit["metrics"]["ecg_self_C_minus_B"] == 0.5


def test_v2final_offline_audit_rejects_unpaired_budget_metadata() -> None:
    rows = [
        _audit_row(condition, task_id, candidate_answer="11")
        for condition in ("generic_closed_loop_v2final", "endogenous_executive_v2final")
        for task_id in ("reasoning_06", "reasoning_07")
    ]
    rows[-1]["call_tokens"] = 255
    with pytest.raises(ValueError, match="row_call_tokens_mismatch"):
        audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))


def test_v2final_offline_audit_markdown_preserves_null_task_ecg() -> None:
    rows = [
        _audit_row(condition, task_id)
        for condition in ("generic_closed_loop_v2final", "endogenous_executive_v2final")
        for task_id in ("reasoning_06", "reasoning_07")
    ]
    audit = audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))
    markdown = render_markdown(audit, "genesis_v2final_result.json")
    assert "AUDIT_INCONCLUSIVE_MISSING_CANDIDATE_ANSWER" in markdown
    assert "External accuracy no último candidate | null | null" in markdown
    assert "ausente" in markdown



def test_v2final_offline_audit_accepts_explicit_response_after_vm_error() -> None:
    rows = [
        _audit_row("generic_closed_loop_v2final", "reasoning_06"),
        _audit_row("generic_closed_loop_v2final", "reasoning_07"),
        _audit_row("endogenous_executive_v2final", "reasoning_06"),
        _audit_row("endogenous_executive_v2final", "reasoning_07"),
    ]
    for row, response in zip(rows, ("11", "54", "11", "162"), strict=True):
        row["response"] = response
    audit = audit_payload(_audit_payload(rows), _load_public_tasks(ROOT))
    assert audit["decision"] == "AUDIT_COMPLETE"
    assert audit["metrics"]["B_fixed_executive"]["external_accuracy"] == 0.5
    assert audit["metrics"]["C_endogenous_executive"]["external_accuracy"] == 1.0
    assert all(row["candidate_source"] == "row.response" for row in audit["rows"])
