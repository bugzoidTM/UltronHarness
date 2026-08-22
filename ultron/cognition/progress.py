"""Detecção determinística de progresso, estagnação e loops de ação Horizon."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProgressTracker:
    stagnation_limit: int = 4
    action_loop_limit: int = 3
    stagnant_iterations: int = 0
    action_counts: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def signature(tool: str | None, arguments: dict[str, Any], evidence_state: list[str]) -> str:
        payload = json.dumps(
            {"tool": tool, "arguments": arguments, "evidence": sorted(evidence_state)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_action(self, tool: str | None, arguments: dict[str, Any], evidence_state: list[str], *, effective: bool) -> tuple[bool, bool]:
        signature = self.signature(tool, arguments, evidence_state)
        if effective:
            self.stagnant_iterations = 0
            self.action_counts[signature] = 0
            return False, False
        self.stagnant_iterations += 1
        self.action_counts[signature] = self.action_counts.get(signature, 0) + 1
        action_loop = self.action_counts[signature] >= self.action_loop_limit
        stagnation = self.stagnant_iterations >= self.stagnation_limit
        return action_loop, stagnation
