"""Registry determinístico de verificadores seguros para etapas e missões."""

from __future__ import annotations

import json
from collections.abc import Callable
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


@dataclass(frozen=True, slots=True)
class TaskSuccessContract:
    required_conditions: tuple[str, ...] = ()


Verifier = Callable[[str, dict[str, Any], dict[str, Any] | None, bool], list[Evidence]]


class StepSuccessVerifier:
    """Aceita somente predicados registrados; texto do modelo nunca é evidência."""

    def __init__(self, tools: ToolRegistry, critic: EvidenceCritic | None = None):
        self.tools = tools
        self.critic = critic or EvidenceCritic()
        self.registry: dict[str, Verifier] = {
            "tool_exit_zero": self._tool_exit_zero,
            "prior_steps_completed": self._prior_steps_completed,
            "task_context": self._task_context,
            "file_exists": self._file_exists,
            "file_contains": self._file_contains,
            "json_schema": self._json_schema,
            "manifest_files": self._manifest_files,
            "registered_command": self._registered_command,
        }

    def _safe_path(self, workspace: str, raw_path: str) -> Path | None:
        root = self.tools.workspace_for(workspace)
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _split(condition: str) -> tuple[str, str]:
        name, separator, argument = condition.partition(":")
        return name, argument if separator else ""

    def _tool_exit_zero(self, _argument: str, _task: dict[str, Any], result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        return [Evidence("exit_code", 0 if result and result.get("status") == "completed" else 1, "tool_execution")]

    def _prior_steps_completed(self, _argument: str, _task: dict[str, Any], _result: dict[str, Any] | None, prior: bool) -> list[Evidence]:
        return [Evidence("test_passed", prior, "plan_state")]

    def _task_context(self, _argument: str, task: dict[str, Any], _result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        return [Evidence("test_passed", bool(task.get("objective") and task.get("workspace")), "task_metadata")]

    def _file_exists(self, argument: str, task: dict[str, Any], _result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        path = self._safe_path(str(task["workspace"]), argument.strip())
        return [Evidence("file_exists", bool(path and path.is_file()), str(path) if path else "outside_workspace")]

    def _file_contains(self, argument: str, task: dict[str, Any], _result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        path_text, separator, expected = argument.partition("::")
        path = self._safe_path(str(task["workspace"]), path_text.strip())
        matches = bool(separator and path and path.is_file() and expected in path.read_text(encoding="utf-8", errors="replace"))
        return [Evidence("test_passed", matches, str(path) if path else "outside_workspace")]

    def _json_schema(self, argument: str, task: dict[str, Any], _result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        path_text, separator, required = argument.partition("::")
        path = self._safe_path(str(task["workspace"]), path_text.strip())
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() and separator else None
            keys = [key.strip() for key in required.split(",") if key.strip()]
            accepted = isinstance(payload, dict) and all(key in payload for key in keys)
        except json.JSONDecodeError:
            accepted = False
        return [Evidence("test_passed", accepted, str(path) if path else "outside_workspace")]

    def _manifest_files(self, argument: str, task: dict[str, Any], _result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        manifest_path, separator, required = argument.partition("::")
        path = self._safe_path(str(task["workspace"]), manifest_path.strip())
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() and separator else None
            listed = set(payload.get("files", [])) if isinstance(payload, dict) else set()
            wanted = {item.strip() for item in required.split(",") if item.strip()}
            accepted = wanted.issubset(listed)
        except json.JSONDecodeError:
            accepted = False
        return [Evidence("test_passed", accepted, str(path) if path else "outside_workspace")]

    def _registered_command(self, argument: str, _task: dict[str, Any], result: dict[str, Any] | None, _prior: bool) -> list[Evidence]:
        command_name = argument.strip()
        metadata = result.get("metadata", {}) if result else {}
        accepted = bool(result and result.get("status") == "completed" and metadata.get("registered_verifier") == command_name)
        return [Evidence("exit_code", 0 if accepted else 1, f"registered:{command_name}")]

    def verify(self, step: PlanStep, task: dict[str, Any], tool_result: dict[str, Any] | None, *, prior_steps_verified: bool) -> StepVerification:
        condition = step.success_condition.strip()
        name, argument = self._split(condition)
        verifier = self.registry.get(name)
        evidence = verifier(argument, task, tool_result, prior_steps_verified) if verifier else []
        result: CriticResult = self.critic.assess(evidence)
        return StepVerification(result.accepted is True, result.basis, result.evidence, condition)

    def verify_task_contract(self, contract: TaskSuccessContract, task: dict[str, Any], *, prior_steps_verified: bool) -> StepVerification:
        evidence: list[Evidence] = []
        for condition in contract.required_conditions:
            name, argument = self._split(condition)
            verifier = self.registry.get(name)
            if verifier is None:
                return StepVerification(False, "verifier_not_registered", (), condition)
            evidence.extend(verifier(argument, task, None, prior_steps_verified))
        result = self.critic.assess(evidence)
        return StepVerification(result.accepted is True, result.basis, result.evidence, "task_success_contract")
