from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultron.genesis.schemas import (
    CognitiveFrame,
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
            output = await self._structured(
                HypothesisOutput,
                "Proponha hipóteses candidatas e previsões testáveis a partir do frame atual. Não escolha nem anuncie uma resposta final.",
                frame,
            )
            frame.hypotheses = output.hypotheses
            frame.predictions = output.predictions
            return
        if operator == "DEDUCT":
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
