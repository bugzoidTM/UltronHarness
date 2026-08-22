"""Autoridade explícita de outcome: evidência externa e verificadores vencem alegações do modelo."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ultron.schemas import OutcomeResult


class OutcomeAuthority:
    """Resolve sucesso de missão pelo nível de evidência mais alto disponível."""

    levels = (
        "private_mission_evaluator",
        "task_success_contract",
        "task_registered_verifier",
        "verified_required_subgoals",
        "action_verifier",
        "tool_success",
        "model_claim",
    )

    def decide(
        self,
        *,
        private_evaluation: dict[str, Any] | None = None,
        task_contract: dict[str, Any] | None = None,
        task_verifier: dict[str, Any] | None = None,
        required_subgoals_verified: bool | None = None,
        action_verified: bool | None = None,
        tool_succeeded: bool | None = None,
        model_claim: bool | None = None,
    ) -> OutcomeResult:
        if private_evaluation is not None:
            return OutcomeResult(
                success=bool(private_evaluation.get("passed")),
                authority_level="private_mission_evaluator",
                evidence_refs=[str(item) for item in private_evaluation.get("evidence", [])],
                confidence=1.0,
                final=True,
            )
        if task_contract is not None:
            return self._from_evidence(task_contract, "task_success_contract")
        if task_verifier is not None:
            return self._from_evidence(task_verifier, "task_registered_verifier")
        if required_subgoals_verified is not None:
            return OutcomeResult(
                success=required_subgoals_verified,
                authority_level="verified_required_subgoals",
                evidence_refs=[],
                confidence=0.9,
                final=True,
            )
        if action_verified is not None:
            return OutcomeResult(
                success=action_verified,
                authority_level="action_verifier",
                evidence_refs=[],
                confidence=0.75,
                final=False,
            )
        if tool_succeeded is not None:
            return OutcomeResult(
                success=tool_succeeded,
                authority_level="tool_success",
                evidence_refs=[],
                confidence=0.5,
                final=False,
            )
        return OutcomeResult(
            success=bool(model_claim),
            authority_level="model_claim",
            evidence_refs=[],
            confidence=0.2,
            final=False,
        )

    @staticmethod
    def allows_verified_writeback(result: OutcomeResult, *, minimum_level: str = "task_registered_verifier") -> bool:
        try:
            result_rank = OutcomeAuthority.levels.index(result.authority_level)
            minimum_rank = OutcomeAuthority.levels.index(minimum_level)
        except ValueError:
            return False
        return result.success and result.final and result_rank <= minimum_rank

    @staticmethod
    def _from_evidence(evidence: dict[str, Any], level: str) -> OutcomeResult:
        return OutcomeResult(
            success=bool(evidence.get("accepted", evidence.get("success", False))),
            authority_level=level,
            evidence_refs=[str(item) for item in evidence.get("evidence", [])],
            confidence=float(evidence.get("confidence", 1.0)),
            final=True,
        )


OutcomeEvaluator = Callable[..., OutcomeResult]
