from __future__ import annotations

import json
from typing import Any

from ultron.genesis.schemas import GENESIS_OPERATORS, CognitiveProgramBatch


class CognitiveProgramSynthesizer:
    """Solicita ao mesmo modelo uma organização de operadores não solucionadores."""

    def __init__(self, gateway: Any, *, model_name: str, seed: int, max_tokens: int) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.seed = seed
        self.max_tokens = max_tokens
        self.calls = 0

    @staticmethod
    def _messages(diagnosis: list[dict[str, Any]], max_programs: int, max_operators: int) -> list[dict[str, str]]:
        system = (
            "Você é um sintetizador de Cognitive Programs para uma VM não solucionadora. "
            "Crie sequências usando somente as quatro primitivas fornecidas. "
            "Não use código, ferramentas, internet, memória externa, gabaritos ou operações fora da lista. "
            "Cada primitiva chama o mesmo modelo com um schema estruturado; a VM não conhece a semântica das tarefas. "
            "Responda somente o schema JSON."
        )
        user = {
            "task": "Com base apenas nas falhas observadas no diagnóstico, proponha organizações de raciocínio para a VM.",
            "primitive_operators": list(GENESIS_OPERATORS),
            "max_programs": max_programs,
            "max_operators_per_program": max_operators,
            "diagnosis_observations": diagnosis,
            "constraints": [
                "cada programa deve conter de 1 a max_operators operadores",
                "somente REPRESENT, HYPOTHESIZE, DEDUCT e VERIFY são permitidos",
                "não invente gabaritos nem respostas prontas",
                "o rationale é auditoria e não será usado pela VM",
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


class AdaptivePolicySynthesizer:
    """Solicita ao modelo uma política de transições finita, sem ações externas."""

    def __init__(self, gateway: Any, *, model_name: str, seed: int, max_tokens: int) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.seed = seed
        self.max_tokens = max_tokens
        self.calls = 0

    @staticmethod
    def _messages(diagnosis: list[dict[str, Any]], max_decisions: int, max_rules: int) -> list[dict[str, str]]:
        system = (
            "Você é um sintetizador de políticas cognitivas adaptativas para uma VM fechada. "
            "Retorne somente uma política JSON finita. Use exclusivamente REPRESENT, HYPOTHESIZE, DEDUCT e VERIFY. "
            "As condições são predicados estruturais do estado; não use código, ferramentas, internet, memória externa, "
            "gabaritos ou semântica de domínio. STOP não é operador: verification_supported encerra a VM."
        )
        user = {
            "task": "Com base somente nas observações públicas do diagnóstico, proponha regras que escolham a próxima operação a partir do estado atual.",
            "allowed_operators": list(GENESIS_OPERATORS),
            "allowed_conditions": [
                "no_representation",
                "has_facts",
                "no_hypothesis",
                "has_hypothesis",
                "no_candidate",
                "has_candidate",
                "verification_supported",
                "verification_contradicted",
                "verification_uncertain",
            ],
            "max_decisions": max_decisions,
            "max_rules": max_rules,
            "required_condition_set": [
                "no_representation",
                "no_hypothesis",
                "no_candidate",
                "has_candidate",
                "verification_contradicted",
                "verification_uncertain",
            ],
            "required_operator_mappings": {
                "no_representation": "REPRESENT",
                "no_hypothesis": "HYPOTHESIZE",
                "no_candidate": "DEDUCT",
                "has_candidate": "VERIFY",
                "verification_contradicted": "DEDUCT or HYPOTHESIZE",
                "verification_uncertain": "DEDUCT or HYPOTHESIZE",
            },
            "diagnosis_observations": diagnosis,
            "constraints": [
                "cada regra contém de 1 a 3 condições",
                "cada regra aponta para exatamente uma das quatro primitivas",
                "prioridades são inteiros únicos; a menor prioridade vence",
                "não crie STOP nem transições externas",
                "a primeira regra deve ser priority=0, conditions=[no_representation], operator=REPRESENT",
                "inclua uma regra aplicável a cada estado de feedback que pretenda tratar",
                "rationale é auditoria e não é executado",
            ],
        }
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]

    async def generate(self, diagnosis: list[dict[str, Any]], *, max_decisions: int = 6, max_rules: int = 8) -> Any:
        self.calls += 1
        from ultron.genesis.schemas import CognitivePolicy

        return await self.gateway.structured(
            CognitivePolicy,
            self._messages(diagnosis, max_decisions, max_rules),
            self.model_name,
            seed=self.seed,
            max_tokens=self.max_tokens,
            temperature=0.2,
            repair_attempts=2,
        )
