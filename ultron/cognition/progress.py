"""Detecção determinística de progresso e loops por estado observável estável."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ultron.schemas import ProgressSignal

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


@dataclass(slots=True)
class ProgressTracker:
    stagnation_limit: int = 4
    action_loop_limit: int = 3
    stagnant_iterations: int = 0
    action_counts: dict[str, int] = field(default_factory=dict)
    seen_observations: set[str] = field(default_factory=set)

    @staticmethod
    def stable_digest(observations: list[str]) -> str:
        normalized = [_UUID.sub("<id>", item) for item in observations[-8:]]
        return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()

    @classmethod
    def signature(cls, tool: str | None, arguments: dict[str, Any], observations: list[str]) -> str:
        payload = json.dumps({"tool": tool, "arguments": arguments, "observable_state": cls.stable_digest(observations)}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def reset_for_reorientation(self) -> None:
        """Reinicia somente os contadores de repetição após uma mudança explícita de estratégia."""
        self.stagnant_iterations = 0
        self.action_counts.clear()

    def assess(self, *, tool: str | None, arguments: dict[str, Any], observations: list[str], output: str, verification_passed: bool, subgoal_completed: bool) -> tuple[bool, bool, ProgressSignal]:
        fingerprint = hashlib.sha256(_UUID.sub("<id>", output).encode("utf-8")).hexdigest()
        novel = bool(output.strip()) and fingerprint not in self.seen_observations
        if novel:
            self.seen_observations.add(fingerprint)
        progressed = novel or subgoal_completed
        reasons = (["new_observation"] if novel else []) + (["subgoal_verified"] if subgoal_completed else [])
        signal = ProgressSignal(progressed=progressed, reasons=reasons, evidence_refs=[])
        signature = self.signature(tool, arguments, observations)
        if progressed:
            self.stagnant_iterations = 0
            self.action_counts[signature] = 0
            return False, False, signal
        self.stagnant_iterations += 1
        self.action_counts[signature] = self.action_counts.get(signature, 0) + 1
        return self.action_counts[signature] >= self.action_loop_limit, self.stagnant_iterations >= self.stagnation_limit, signal
