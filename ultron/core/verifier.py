"""Verificação determinística, por etapa, das condições de sucesso do plano.

A gramática é intencionalmente pequena para evitar que uma frase do modelo seja
tratada como prova: `tool_exit_zero`, `file_exists:<caminho>`,
`file_contains:<caminho>::<texto>`, `prior_steps_completed` e `task_context`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultron.cognition.critic import CriticResult, Evidence, EvidenceCritic
from ultron.schemas import PlanStep
from ultron.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class StepVerification:
    accepted: bool
    basis: str
    evidence: tuple[Evidence, ...]
    condition: str


class StepSuccessVerifier:
    """Nunca usa texto de modelo como juiz de conclusão de uma etapa."""

    def __init__(self, tools: ToolRegistry, critic: EvidenceCritic | None = None):
        self.tools = tools
        self.critic = critic or EvidenceCritic()

    def _safe_path(self, workspace: str, raw_path: str) -> Path | None:
        root = self.tools.workspace_for(workspace)
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    def _evidence(
        self,
        step: PlanStep,
        task: dict[str, Any],
        tool_result: dict[str, Any] | None,
        prior_steps_verified: bool,
    ) -> list[Evidence]:
        condition = step.success_condition.strip()
        if condition == "tool_exit_zero":
            return [Evidence("exit_code", 0 if tool_result and tool_result.get("status") == "completed" else 1, "tool_execution")]
        if condition == "prior_steps_completed":
            return [Evidence("test_passed", prior_steps_verified, "plan_state")]
        if condition == "task_context":
            return [Evidence("test_passed", bool(task.get("objective") and task.get("workspace")), "task_metadata")]
        if condition.startswith("file_exists:"):
            path = self._safe_path(str(task["workspace"]), condition.removeprefix("file_exists:").strip())
            return [Evidence("file_exists", bool(path and path.is_file()), str(path) if path else "outside_workspace")]
        if condition.startswith("file_contains:"):
            specification = condition.removeprefix("file_contains:")
            path_text, separator, expected = specification.partition("::")
            path = self._safe_path(str(task["workspace"]), path_text.strip())
            matches = bool(separator and path and path.is_file() and expected in path.read_text(encoding="utf-8", errors="replace"))
            return [Evidence("test_passed", matches, str(path) if path else "outside_workspace")]
        return []

    def verify(
        self,
        step: PlanStep,
        task: dict[str, Any],
        tool_result: dict[str, Any] | None,
        *,
        prior_steps_verified: bool,
    ) -> StepVerification:
        evidence = self._evidence(step, task, tool_result, prior_steps_verified)
        result: CriticResult = self.critic.assess(evidence)
        accepted = result.accepted is True
        return StepVerification(accepted, result.basis, result.evidence, step.success_condition)
