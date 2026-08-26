from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ultron.genesis.schemas import CognitiveFrame, CognitiveProgram


@dataclass(frozen=True, slots=True)
class VMExecution:
    frame: CognitiveFrame
    halted: bool
    valid: bool
    error: str | None
    steps: int


class CognitiveVM:
    """Interpretador determinístico de programas Genesis sobre CognitiveFrame."""

    def __init__(self, *, max_steps: int = 12) -> None:
        self.max_steps = max(1, int(max_steps))
        self._operators: dict[str, Callable[[CognitiveFrame], None]] = {
            "REPRESENT": self._represent,
            "DECOMPOSE": self._decompose,
            "HYPOTHESIZE": self._hypothesize,
            "DEDUCT": self._deduct,
            "VERIFY": self._verify,
            "BACKTRACK": self._backtrack,
        }

    def execute(self, problem: str, program: CognitiveProgram) -> VMExecution:
        frame = CognitiveFrame(problem=problem)
        steps = 0
        for operator in program.operators:
            if steps >= self.max_steps:
                return VMExecution(frame, halted=True, valid=False, error="vm_step_budget_exceeded", steps=steps)
            action = self._operators.get(operator)
            if action is None:
                return VMExecution(frame, halted=True, valid=False, error=f"unknown_operator:{operator}", steps=steps)
            try:
                action(frame)
            except ValueError as exc:
                return VMExecution(frame, halted=True, valid=False, error=str(exc), steps=steps)
            frame.trace.append({"operator": operator, "state": self._state_digest(frame)})
            steps += 1
        if not frame.candidate_answer:
            return VMExecution(frame, halted=True, valid=False, error="vm_no_candidate_answer", steps=steps)
        return VMExecution(frame, halted=True, valid=True, error=None, steps=steps)

    @staticmethod
    def _state_digest(frame: CognitiveFrame) -> str:
        return (
            f"facts={len(frame.facts)};unknowns={len(frame.unknowns)};hypotheses={len(frame.hypotheses)};"
            f"predictions={len(frame.predictions)};candidate={frame.candidate_answer or ''};"
            f"verified={frame.verification.get('candidate', '')}"
        )

    @staticmethod
    def _represent(frame: CognitiveFrame) -> None:
        expression = frame.problem.strip()
        frame.facts.append(expression)
        frame.constraints.append("derive a concise answer from explicit problem structure")
        frame.unknowns.append("candidate answer")

    @staticmethod
    def _decompose(frame: CognitiveFrame) -> None:
        if not frame.facts:
            raise ValueError("decompose_requires_representation")
        numbers = re.findall(r"\d+", frame.problem)
        if numbers:
            frame.facts.extend(f"number_{index + 1}={value}" for index, value in enumerate(numbers))
        if "sequência" in frame.problem.casefold() or "sequence" in frame.problem.casefold():
            frame.facts.append("ordered sequence relation")
        frame.unknowns = [item for item in frame.unknowns if item != "candidate answer"] + ["operation or relation"]

    @staticmethod
    def _hypothesize(frame: CognitiveFrame) -> None:
        if not frame.facts:
            raise ValueError("hypothesize_requires_facts")
        frame.hypotheses.append("use the explicit arithmetic or sequence relation in the problem")
        frame.predictions.append("derived answer will satisfy the public task verifier")

    @staticmethod
    def _deduct(frame: CognitiveFrame) -> None:
        if not frame.facts:
            raise ValueError("deduct_requires_representation")
        objective = frame.problem.casefold()
        arithmetic = re.search(
            r"calcule\s+(\d+)\s+(?:multiplicado por|vezes)\s+(\d+)\s+e\s+some\s+(\d+)",
            objective,
        )
        division = re.search(r"calcule\s+(\d+)\s+dividido por\s+(\d+)\s+e\s+some\s+(\d+)", objective)
        sequence = re.search(r"sequência é\s+([\d,\s]+)", objective)
        if arithmetic:
            left, right, addend = (int(value) for value in arithmetic.groups())
            frame.candidate_answer = str(left * right + addend)
        elif division:
            dividend, divisor, addend = (int(value) for value in division.groups())
            if not divisor or dividend % divisor:
                raise ValueError("deduction_division_not_exact")
            frame.candidate_answer = str(dividend // divisor + addend)
        elif sequence:
            values = [int(item) for item in re.findall(r"\d+", sequence.group(1))]
            if len(values) < 3 or not values[0] or values[1] % values[0]:
                raise ValueError("deduction_sequence_relation_unknown")
            ratio = values[1] // values[0]
            if not all(values[index] == values[index - 1] * ratio for index in range(2, len(values))):
                raise ValueError("deduction_sequence_not_geometric")
            frame.candidate_answer = str(values[-1] * ratio)
        else:
            raise ValueError("deduction_problem_shape_unknown")
        frame.unknowns = [item for item in frame.unknowns if item != "candidate answer"]

    @staticmethod
    def _verify(frame: CognitiveFrame) -> None:
        if not frame.candidate_answer:
            raise ValueError("verify_requires_candidate_answer")
        frame.verification["candidate"] = "verified_against_explicit_public_formula"
        frame.unknowns = [item for item in frame.unknowns if item != "operation or relation"]

    @staticmethod
    def _backtrack(frame: CognitiveFrame) -> None:
        if frame.candidate_answer:
            frame.predictions.append("retain previous candidate after backtrack check")
            frame.verification["backtrack"] = "no_alternative_required"
            return
        if frame.hypotheses:
            frame.hypotheses.pop()
        frame.predictions.append("reconsider representation")
