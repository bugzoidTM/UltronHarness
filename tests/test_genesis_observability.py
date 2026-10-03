from __future__ import annotations

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from scripts.audit_genesis_v2final import _load_public_tasks, audit_payload
from scripts.run_genesis_v2final import _record
from scripts.run_genesis_v2final_obs import (
    ModelUnavailableError,
    _run,
    evaluate_gate,
    model_identity,
)
from tests.test_genesis_ablation import _FeedbackGateway
from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import Settings, load_settings
from ultron.genesis.public_runner import GenesisPublicRunner, candidate_observation
from ultron.genesis.schemas import VerificationOutput
from ultron.genesis.vm import EndogenousExecutiveVM, GenericClosedLoopVM

ROOT = Path(__file__).resolve().parents[1]
TASK = BenchmarkTask(id="reasoning_06", category="reasoning", objective="Calcule 24 dividido por 6 e some 7.", evaluator="exact")


def _runner(tmp_path: Path, gateway: object) -> GenesisPublicRunner:
    runner = GenesisPublicRunner(Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path))
    runner.models = gateway
    return runner


class _SlowVerifyGateway(_FeedbackGateway):
    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        if schema is VerificationOutput:
            self.calls.append({"schema": schema.__name__})
            await asyncio.sleep(5)
        return await super().structured(schema, messages, model_name, **kwargs)


class _SchemaFailureGateway(_FeedbackGateway):
    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        if schema is VerificationOutput:
            return VerificationOutput.model_validate_json('{"status": "maybe"}')
        return await super().structured(schema, messages, model_name, **kwargs)


class _TransportFailureGateway(_FeedbackGateway):
    async def structured(self, schema: type[object], messages: list[dict[str, str]], model_name: str, **kwargs: object) -> object:
        if schema is VerificationOutput:
            raise httpx.ConnectError("runtime down")
        return await super().structured(schema, messages, model_name, **kwargs)


def test_candidate_survives_hypothesize_reset() -> None:
    gateway = _FeedbackGateway(["contradicted", "contradicted"])
    result = asyncio.run(
        GenericClosedLoopVM(gateway, model_name="fake", seed=42, max_tokens=256, max_steps=5).execute_closed_loop(TASK.objective, max_decisions=5)
    )
    assert [entry["operator"] for entry in result.frame.trace] == ["REPRESENT", "HYPOTHESIZE", "DEDUCT", "VERIFY", "HYPOTHESIZE"]
    assert result.valid is False
    assert result.frame.candidate_answer is None
    assert result.candidate_history == ("wrong",)
    assert result.last_candidate_answer == "wrong"


def test_budget_exceeded_row_serializes_last_candidate(tmp_path: Path) -> None:
    runner = _runner(tmp_path, _FeedbackGateway(["contradicted", "contradicted"]))
    result = asyncio.run(runner.run_one(task=TASK, condition="endogenous_executive_v2final", run_id="obs", model_name="fake", seed=42, max_tokens=1792, decision_budget=7))
    row = _record(result)
    assert row["termination_reason"] == "decision_budget_exceeded"
    assert row["response"] == ""
    assert row["score"] == 0.0
    assert row["candidate_observability"] == "complete"
    assert row["candidate_history"] == ["wrong", "11", "11"]
    assert row["candidate_answer"] == "11"
    assert row["final_verification_status"] == ""  # o último DEDUCT ainda não foi verificado
    assert [entry["verification_status"] for entry in row["trace"] if entry["operator"] == "VERIFY"] == ["contradicted", "contradicted"]
    assert row["failure_class"] == "cognitive"


def test_timeout_preserves_partial_frame_and_candidate(tmp_path: Path) -> None:
    gateway = _SlowVerifyGateway(["supported"])
    runner = _runner(tmp_path, gateway)
    result = asyncio.run(runner.run_one(task=TASK, condition="generic_closed_loop_v2final", run_id="obs", model_name="fake", seed=42, max_tokens=1792, decision_budget=7, call_timeout_seconds=0.05))
    observed = candidate_observation(result)
    assert result.execution.failure_category == "TIMEOUT"
    assert result.vm_execution is not None
    assert result.vm_execution.termination_reason == "timeout"
    assert result.vm_execution.decisions == 3
    assert result.vm_execution.model_calls == 4
    assert observed["candidate_answer"] == "11"
    assert observed["failure_class"] == "infra"


def test_fixed_executive_trace_is_as_observable_as_endogenous() -> None:
    gateway = _FeedbackGateway(["uncertain", "supported"])
    fixed = asyncio.run(GenericClosedLoopVM(gateway, model_name="fake", seed=42, max_tokens=256).execute_closed_loop(TASK.objective, max_decisions=7))
    endogenous = asyncio.run(EndogenousExecutiveVM(_FeedbackGateway(["uncertain", "supported"]), model_name="fake", seed=42, max_tokens=256).execute_online(TASK.objective, max_decisions=7))
    for execution in (fixed, endogenous):
        assert all({"candidate_answer", "verification_status"} <= set(entry) for entry in execution.frame.trace)
        assert [entry["verification_status"] for entry in execution.frame.trace if entry["operator"] == "VERIFY"] == ["uncertain", "supported"]


def test_observability_fields_never_reach_model_messages(tmp_path: Path) -> None:
    gateway = _FeedbackGateway(["contradicted", "supported"])
    runner = _runner(tmp_path, gateway)
    asyncio.run(runner.run_one(task=TASK, condition="generic_closed_loop_v2final", run_id="obs", model_name="fake", seed=42, max_tokens=1792, decision_budget=7))
    contents = [message["content"] for call in gateway.calls for message in call["messages"]]
    assert contents
    for forbidden in ("'trace'", "candidate_history", "generic_fixed_feedback", "verification_status="):
        assert all(forbidden not in content for content in contents)


@pytest.mark.parametrize(
    ("gateway", "expected"),
    [(_SchemaFailureGateway(["supported"]), "cognitive"), (_TransportFailureGateway(["supported"]), "infra")],
)
def test_failure_class_separates_schema_from_transport(tmp_path: Path, gateway: _FeedbackGateway, expected: str) -> None:
    runner = _runner(tmp_path, gateway)
    result = asyncio.run(runner.run_one(task=TASK, condition="endogenous_executive_v2final", run_id="obs", model_name="fake", seed=42, max_tokens=1792, decision_budget=7))
    observed = candidate_observation(result)
    assert result.execution.failure_category == "VM_ERROR"
    assert observed["failure_class"] == expected
    assert observed["candidate_answer"] == "11"


def _gate_row(label: str, task_id: str, *, valid: bool, success: bool, candidate_ok: bool, failure_class: str = "none") -> dict[str, object]:
    return {
        "task_id": task_id,
        "condition_label": label,
        "row_status": "run",
        "operationally_valid": valid,
        "success": success,
        "candidate_answer": "x",
        "candidate_external_success": candidate_ok,
        "final_frame_candidate_external_success": candidate_ok,
        "termination_reason": "verification_supported" if valid else "decision_budget_exceeded",
        "final_verification_status": "supported" if valid else "uncertain",
        "recovery_attempted": False,
        "recovered": False,
        "decisions": 4 if valid else 7,
        "failure_class": failure_class if not valid else "none",
    }


def _primary(b: list[tuple[bool, bool, bool]], c: list[tuple[bool, bool, bool]]) -> dict[str, list[dict[str, object]]]:
    ids = ("reasoning_06", "reasoning_07")
    return {
        "B_fixed_executive": [_gate_row("B_fixed_executive", task_id, valid=v, success=s, candidate_ok=k, failure_class="cognitive") for task_id, (v, s, k) in zip(ids, b, strict=True)],
        "C_endogenous_executive": [_gate_row("C_endogenous_executive", task_id, valid=v, success=s, candidate_ok=k, failure_class="cognitive") for task_id, (v, s, k) in zip(ids, c, strict=True)],
    }


def test_gate_go_replicate_requires_all_rows_valid_and_positive_ecg() -> None:
    gate = evaluate_gate(_primary([(True, True, True), (True, False, False)], [(True, True, True), (True, True, True)]), [])
    assert gate["gate"] == "GO_REPLICATE"
    assert gate["ecg_C_minus_B"] == 0.5
    assert gate["ecg_task_C_minus_B"] == 0.5


def test_gate_invalid_execution_still_reports_task_ecg() -> None:
    gate = evaluate_gate(_primary([(False, False, False), (False, False, True)], [(False, False, True), (False, False, True)]), [])
    assert gate["gate"] == "REJECTED_INVALID_EXECUTION"
    assert gate["ecg_C_minus_B"] is None
    assert gate["ecg_task_C_minus_B"] == 0.5
    assert gate["ecg_self_C_minus_B"] == 0.0


def test_gate_partial_validity_and_non_positive_ecg() -> None:
    assert evaluate_gate(_primary([(True, True, True), (False, False, False)], [(True, True, True), (True, True, True)]), [])["gate"] == "PARTIAL_VALIDITY"
    assert evaluate_gate(_primary([(True, True, True), (True, True, True)], [(True, True, True), (True, True, True)]), [])["gate"] == "NO_GO"


def test_gate_infra_failure_or_missing_row_blocks_every_delta() -> None:
    primary = _primary([(False, False, True), (True, True, True)], [(True, True, True), (True, True, True)])
    primary["B_fixed_executive"][0]["failure_class"] = "infra"
    gate = evaluate_gate(primary, [])
    assert gate["gate"] == "INFRA_INVALID"
    assert gate["ecg_task_C_minus_B"] is None and gate["ecg_self_C_minus_B"] is None
    primary = _primary([(True, True, True), (True, True, True)], [(True, True, True), (True, True, True)])
    primary["C_endogenous_executive"][1] = {"task_id": "reasoning_07", "row_status": "not_run", "failure_class": "infra", "operationally_valid": False}
    assert evaluate_gate(primary, [])["gate"] == "INFRA_INVALID"


def test_obs_fixture_serializes_complete_rows(tmp_path: Path) -> None:
    args = argparse.Namespace(mode="fixture", model="ollama_research_7b", output=tmp_path, call_timeout_seconds=None, global_timeout_seconds=540, http_timeout_seconds=None, skip_direct_reference=False)
    assert asyncio.run(_run(args)) == 0
    payload = json.loads((tmp_path / "genesis_v2final_obs_result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["gate"] == "DEVELOPMENT_ONLY"
    assert payload["cognitive_contract"] == "genesis-v2-final-executive-control"
    assert payload["automatic_model_download"] is False
    assert len(payload["rows"]) == 4 and len(payload["reference_rows"]) == 2
    assert all(row["candidate_observability"] == "complete" and row["candidate_answer"] == "11" for row in payload["rows"] + payload["reference_rows"])


def test_obs_rows_remain_compatible_with_offline_auditor(tmp_path: Path) -> None:
    runner = _runner(tmp_path, _FeedbackGateway(["uncertain", "uncertain", "uncertain"]))
    rows = []
    for condition in ("generic_closed_loop_v2final", "endogenous_executive_v2final"):
        for task_id in ("reasoning_06", "reasoning_07"):
            task = BenchmarkTask(id=task_id, category="reasoning", objective=TASK.objective, evaluator="exact")
            rows.append(_record(asyncio.run(runner.run_one(task=task, condition=condition, run_id="obs", model_name="fake", seed=42, max_tokens=1792, decision_budget=7))))
    payload = {
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
    audit = audit_payload(payload, _load_public_tasks(ROOT))
    assert audit["decision"] == "AUDIT_COMPLETE"
    assert all(row["candidate_source"] == "row.candidate_answer" for row in audit["rows"])
    assert audit["metrics"]["B_fixed_executive"]["recovery_attempts"] == 2


def test_model_identity_never_downloads_missing_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.0"})
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b", "digest": "abc", "details": {}}]})

    transport = httpx.MockTransport(handler)
    with pytest.raises(ModelUnavailableError, match="model_not_installed:qwen2.5:7b"):
        asyncio.run(model_identity("http://ollama.test", "qwen2.5:7b", transport=transport))
    identity = asyncio.run(model_identity("http://ollama.test", "qwen2.5:3b", transport=transport))
    assert identity["digest"] == "abc"
