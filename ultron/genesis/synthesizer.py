from __future__ import annotations

import json
from typing import Any

from ultron.genesis.schemas import GENESIS_OPERATORS, CognitiveProgramBatch


class CognitiveProgramSynthesizer:
    """Solicita sequências de operadores VM ao mesmo modelo do experimento."""

    def __init__(self, gateway: Any, *, model_name: str, seed: int, max_tokens: int) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.seed = seed
        self.max_tokens = max_tokens
        self.calls = 0

    @staticmethod
    def _messages(diagnosis: list[dict[str, Any]], max_programs: int, max_operators: int) -> list[dict[str, str]]:
        system = (
            "Você é um sintetizador de Cognitive Programs para uma VM fechada. "
            "Crie sequências novas usando somente as primitivas fornecidas. "
            "Não use código, ferramentas, internet, memória externa ou operações fora da lista. "
            "A sequência será interpretada por uma VM; não escreva um roteiro textual para outro modelo. "
            "Responda somente o schema JSON."
        )
        user = {
            "task": "Com base apenas nas falhas observadas no diagnóstico, proponha programas de operadores que possam ser executados pela Cognitive VM.",
            "primitive_operators": list(GENESIS_OPERATORS),
            "max_programs": max_programs,
            "max_operators_per_program": max_operators,
            "diagnosis_observations": diagnosis,
            "constraints": [
                "cada programa deve conter de 1 a max_operators operadores",
                "repetição de operadores é permitida quando fizer parte do algoritmo",
                "não existe operador STOP; a VM termina quando a lista termina",
                "o rationale explica somente a origem da hipótese e não será usado pela VM",
                "não descreva nem invente gabaritos",
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
