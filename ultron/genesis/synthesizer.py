from __future__ import annotations

import json
from typing import Any

from ultron.genesis.schemas import CognitiveProgramBatch


class CognitiveProgramSynthesizer:
    """Solicita programas interpretáveis ao modelo, sem sugerir uma estratégia fixa."""

    def __init__(self, gateway: Any, *, model_name: str, seed: int, max_tokens: int) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.seed = seed
        self.max_tokens = max_tokens
        self.calls = 0

    @staticmethod
    def _messages(diagnosis: list[dict[str, Any]], max_programs: int, max_operators: int) -> list[dict[str, str]]:
        operators = [
            "OBSERVE",
            "IDENTIFY_UNKNOWN",
            "REPRESENT",
            "DECOMPOSE",
            "HYPOTHESIZE",
            "COMPARE",
            "PREDICT",
            "TEST",
            "DEDUCT",
            "BACKTRACK",
            "VERIFY",
            "UPDATE_BELIEF",
            "STOP",
        ]
        system = (
            "Você é um sintetizador de programas cognitivos temporários. "
            "Crie programas novos combinando somente as primitivas fornecidas. "
            "Não use código, ferramentas, internet, memória externa ou operações fora da lista. "
            "Não receba nem solicite respostas esperadas. Responda somente o schema JSON."
        )
        user = {
            "task": "Com base apenas nas falhas observadas no diagnóstico, proponha programas de raciocínio que possam ser testados.",
            "primitive_operators": operators,
            "max_programs": max_programs,
            "max_operators_per_program": max_operators,
            "diagnosis_observations": diagnosis,
            "constraints": [
                "cada programa deve ter uma sequência ordenada de operadores",
                f"STOP é obrigatório, deve ser o último operador e conta no limite total; use no máximo {max_operators - 1} operadores antes dele",
                "não copie um programa de catálogo",
                "não descreva nem invente gabaritos",
                "o rationale deve explicar a relação entre falha observada e sequência proposta",
            ],
        }
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]

    async def generate(self, diagnosis: list[dict[str, Any]], *, max_programs: int, max_operators: int) -> CognitiveProgramBatch:
        self.calls += 1
        return await self.gateway.structured(
            CognitiveProgramBatch,
            self._messages(diagnosis, max_programs, max_operators),
            self.model_name,
            seed=self.seed,
            max_tokens=self.max_tokens,
            temperature=0.2,
            repair_attempts=1,
        )
