from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultron.genesis.schemas import (
    CognitiveFrame,
    CognitivePolicy,
    CognitiveProgram,
    DeductionOutput,
    HypothesisOutput,
    RepresentationOutput,
    VerificationOutput,
)


@dataclass(frozen=True, slots=True)
class VMExecution:
    frame: CognitiveFrame
    halted: bool
    valid: bool
    error: str | None
    steps: int
    model_calls: int = 0
    decisions: int = 0
    termination_reason: str | None = None


class CognitiveVM:
    """VM não solucionadora: cada operador delega ao mesmo modelo via schema."""

    def __init__(
        self,
        gateway: Any,
        *,
        model_name: str,
        seed: int,
        max_tokens: int,
        max_steps: int = 4,
        repair_attempts: int = 0,
    ) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.seed = seed
        self.max_tokens = max(1, int(max_tokens))
        self.max_steps = max(1, int(max_steps))
        self.repair_attempts = max(0, int(repair_attempts))

    async def execute(self, problem: str, program: CognitiveProgram) -> VMExecution:
        frame = CognitiveFrame(problem=problem)
        steps = 0
        model_calls = 0
        for operator in program.operators:
            if steps >= self.max_steps:
                return VMExecution(frame, halted=True, valid=False, error="vm_step_budget_exceeded", steps=steps, model_calls=model_calls)
            try:
                model_calls += 1
                await self._apply_operator(frame, operator)
            except Exception as exc:
                return VMExecution(frame, halted=True, valid=False, error=f"operator_error:{type(exc).__name__}:{str(exc)[:200]}", steps=steps, model_calls=model_calls)
            frame.trace.append({"operator": operator, "state": self._state_digest(frame)})
            steps += 1
        return VMExecution(frame, halted=True, valid=True, error=None, steps=steps, model_calls=model_calls)

    async def _apply_operator(self, frame: CognitiveFrame, operator: str) -> None:
        if operator == "REPRESENT":
            output = await self._structured(
                RepresentationOutput,
                "Transforme o problema em uma representação factual. Extraia entidades, fatos, restrições e incógnitas sem resolver a tarefa.",
                frame,
            )
            frame.entities = output.entities
            frame.facts = output.facts
            frame.constraints = output.constraints
            frame.unknowns = output.unknowns
            return
        if operator == "HYPOTHESIZE":
            frame.candidate_answer = None
            frame.verification = {}
            output = await self._structured(
                HypothesisOutput,
                "Proponha hipóteses candidatas e previsões testáveis a partir do frame atual. Não escolha nem anuncie uma resposta final.",
                frame,
            )
            frame.hypotheses = output.hypotheses
            frame.predictions = output.predictions
            return
        if operator == "DEDUCT":
            frame.verification = {}
            output = await self._structured(
                DeductionOutput,
                "Dado o frame atual, derive a próxima conclusão justificada. Retorne somente uma conclusão curta; não use ferramentas nem conhecimento de gabarito.",
                frame,
            )
            frame.candidate_answer = output.conclusion
            return
        if operator == "VERIFY":
            output = await self._structured(
                VerificationOutput,
                "Avalie a conclusão candidata contra o problema, os fatos e as restrições disponíveis. Classifique apenas como supported, contradicted ou uncertain.",
                frame,
            )
            frame.verification = {"status": output.status, "explanation": output.explanation}
            return
        raise ValueError(f"unknown_operator:{operator}")

    async def _structured(self, schema: type[Any], instruction: str, frame: CognitiveFrame) -> Any:
        return await self.gateway.structured(
            schema,
            self._messages(instruction, frame),
            self.model_name,
            seed=self.seed,
            max_tokens=self.max_tokens,
            temperature=0.2,
            repair_attempts=self.repair_attempts,
        )

    @staticmethod
    def _messages(instruction: str, frame: CognitiveFrame) -> list[dict[str, str]]:
        visible_frame = frame.model_dump(mode="json", exclude={"trace"})
        return [
            {
                "role": "system",
                "content": (
                    "Você é um operador cognitivo não solucionador. Trabalhe somente sobre o frame fornecido, "
                    "retorne exclusivamente o schema estruturado solicitado e não use ferramentas, arquivos, internet ou gabaritos."
                ),
            },
            {
                "role": "user",
                "content": f"Operação: {instruction}\nFrame atual: {visible_frame}",
            },
        ]

    @staticmethod
    def _state_digest(frame: CognitiveFrame) -> str:
        return (
            f"entities={len(frame.entities)};facts={len(frame.facts)};unknowns={len(frame.unknowns)};"
            f"constraints={len(frame.constraints)};hypotheses={len(frame.hypotheses)};predictions={len(frame.predictions)};"
            f"candidate_present={bool(frame.candidate_answer)};verification_status={frame.verification.get('status', '')}"
        )


class GenericClosedLoopVM(CognitiveVM):
    """Política fixa de feedback usada como controle matched-compute."""

    async def execute_closed_loop(self, problem: str, max_decisions: int = 6) -> VMExecution:
        frame = CognitiveFrame(problem=problem)
        decisions = 0
        model_calls = 0
        while decisions < max_decisions:
            if frame.verification.get("status") == "supported" and frame.candidate_answer:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=True,
                    error=None,
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="verification_supported",
                )
            operator = self._fixed_next_operator(frame)
            try:
                model_calls += 1
                await self._apply_operator(frame, operator)
            except Exception as exc:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=False,
                    error=f"operator_error:{type(exc).__name__}:{str(exc)[:200]}",
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="operator_error",
                )
            frame.trace.append(
                {
                    "operator": operator,
                    "controller": "generic_fixed_feedback",
                    "state": self._state_digest(frame),
                }
            )
            decisions += 1
        return VMExecution(
            frame,
            halted=True,
            valid=False,
            error="closed_loop_decision_budget_exceeded",
            steps=decisions,
            model_calls=model_calls,
            decisions=decisions,
            termination_reason="decision_budget_exceeded",
        )

    @staticmethod
    def _fixed_next_operator(frame: CognitiveFrame) -> str:
        if not frame.entities and not frame.facts and not frame.constraints and not frame.unknowns:
            return "REPRESENT"
        if not frame.hypotheses:
            return "HYPOTHESIZE"
        if frame.verification.get("status") == "contradicted":
            return "HYPOTHESIZE"
        if frame.verification.get("status") == "uncertain":
            return "DEDUCT"
        if not frame.candidate_answer:
            return "DEDUCT"
        return "VERIFY"


class AdaptiveCognitiveVM(CognitiveVM):
    """Interpreta uma política finita: estado, escolha segura, operação e feedback."""

    async def execute_policy(self, problem: str, policy: CognitivePolicy) -> VMExecution:
        frame = CognitiveFrame(problem=problem)
        decisions = 0
        model_calls = 0
        while decisions < policy.max_decisions:
            status = frame.verification.get("status")
            if status == "supported" and frame.candidate_answer:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=True,
                    error=None,
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="verification_supported",
                )
            predicates = self._predicates(frame)
            rule = self._select_rule(policy, predicates)
            if rule is None:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=False,
                    error="policy_no_matching_rule",
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="no_matching_rule",
                )
            try:
                model_calls += 1
                await self._apply_operator(frame, rule.operator)
            except Exception as exc:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=False,
                    error=f"operator_error:{type(exc).__name__}:{str(exc)[:200]}",
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="operator_error",
                )
            frame.trace.append(
                {
                    "operator": rule.operator,
                    "priority": str(rule.priority),
                    "conditions": ",".join(name for name, value in predicates.items() if value),
                    "state": self._state_digest(frame),
                }
            )
            decisions += 1
            if frame.verification.get("status") == "supported" and frame.candidate_answer:
                return VMExecution(
                    frame,
                    halted=True,
                    valid=True,
                    error=None,
                    steps=decisions,
                    model_calls=model_calls,
                    decisions=decisions,
                    termination_reason="verification_supported",
                )
        return VMExecution(
            frame,
            halted=True,
            valid=False,
            error="policy_decision_budget_exceeded",
            steps=decisions,
            model_calls=model_calls,
            decisions=decisions,
            termination_reason="decision_budget_exceeded",
        )

    @staticmethod
    def _predicates(frame: CognitiveFrame) -> dict[str, bool]:
        status = frame.verification.get("status")
        return {
            "no_representation": not frame.entities and not frame.facts and not frame.constraints and not frame.unknowns,
            "has_facts": bool(frame.facts),
            "no_hypothesis": not frame.hypotheses,
            "has_hypothesis": bool(frame.hypotheses),
            "no_candidate": not bool(frame.candidate_answer),
            "has_candidate": bool(frame.candidate_answer),
            "verification_supported": status == "supported",
            "verification_contradicted": status == "contradicted",
            "verification_uncertain": status == "uncertain",
        }

    @staticmethod
    def _select_rule(policy: CognitivePolicy, predicates: dict[str, bool]) -> Any:
        for rule in sorted(policy.rules, key=lambda item: item.priority):
            if all(predicates.get(condition, False) for condition in rule.conditions):
                return rule
        return None
