"""Gera o Transfer-100 com tarefas públicas, contratos e fixtures privados isolados."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer100"

FAMILIES = {
    "structured_validation": {
        "source_domain": "json_validation",
        "target_domain": "yaml_validation",
        "steps": ("P", "C", "R", "A"),
        "actions": {
            "P": "ler a estrutura com o parser permitido",
            "C": "confirmar campos obrigatórios e tipos declarados",
            "R": "rejeitar e registrar a violação observada",
            "A": "aceitar somente após verificações bem-sucedidas",
        },
        "cases": [
            ("O documento não pode ser lido pelo parser.", "P>R"),
            ("O documento é legível, mas um campo obrigatório está ausente.", "P>C>R"),
            ("O documento é legível, mas um campo obrigatório possui tipo incompatível.", "P>C>R"),
            ("O documento é legível e todos os campos obrigatórios têm tipos compatíveis.", "P>C>A"),
        ],
    },
    "dependency_recovery": {
        "source_domain": "python_dependency",
        "target_domain": "node_dependency",
        "steps": ("M", "I", "L", "V", "E"),
        "actions": {
            "M": "inspecionar declaração e resolução de dependências",
            "I": "restaurar somente o recurso explicitamente declarado",
            "L": "restaurar a resolução coerente com a declaração",
            "V": "verificar que a resolução final funciona",
            "E": "registrar que o recurso não é declarado e parar",
        },
        "cases": [
            ("Um recurso declarado está ausente do ambiente resolvido.", "M>I>V"),
            ("A declaração e a resolução registram versões incompatíveis.", "M>L>V"),
            ("Um recurso transitivo está ausente na resolução declarada.", "M>L>V"),
            ("A falha cita um recurso que não está declarado no projeto.", "M>E"),
        ],
    },
    "state_recovery": {
        "source_domain": "filesystem_recovery",
        "target_domain": "repository_state",
        "steps": ("S", "R", "V", "N", "F"),
        "actions": {
            "S": "inspecionar o estado atual antes de modificar",
            "R": "aplicar somente a reversão explicitamente autorizada",
            "V": "confirmar o estado final com evidência",
            "N": "registrar que nenhuma alteração é necessária",
            "F": "registrar falha de confirmação sem ampliar o escopo",
        },
        "cases": [
            ("Um artefato autorizado está modificado e precisa ser restaurado.", "S>R>V"),
            ("O artefato já se encontra no estado solicitado.", "S>N"),
            ("A reversão autorizada ocorreu, mas a verificação ainda mostra divergência.", "S>R>F"),
            ("Somente um dentre vários artefatos é autorizado para recuperação.", "S>R>V"),
        ],
    },
    "planning": {
        "source_domain": "algorithmic_planning",
        "target_domain": "workflow_planning",
        "steps": ("C", "K", "E", "V"),
        "actions": {
            "C": "confirmar evidência de pré-condição",
            "K": "manter a etapa dependente bloqueada",
            "E": "executar a etapa somente após pré-condições",
            "V": "validar a evidência de conclusão",
        },
        "cases": [
            ("A pré-condição obrigatória não possui evidência de conclusão.", "C>K"),
            ("A pré-condição falhou e a etapa seguinte permanece dependente.", "C>K"),
            ("Todas as pré-condições possuem evidência válida para uma etapa dependente.", "C>E>V"),
            ("Uma etapa sem dependências deve registrar evidência de conclusão.", "E>V"),
        ],
    },
    "configuration_repair": {
        "source_domain": "structured_configuration",
        "target_domain": "service_configuration",
        "steps": ("I", "R", "V", "H"),
        "actions": {
            "I": "inspecionar estrutura e valores da configuração",
            "R": "aplicar a reparação mínima explicitamente autorizada",
            "V": "validar a configuração resultante com verificador local",
            "H": "registrar que a mudança solicitada excede a autorização",
        },
        "cases": [
            ("Uma chave obrigatória possui valor ausente e a reparação autorizada é conhecida.", "I>R>V"),
            ("Uma chave possui tipo incompatível e existe reparação mínima autorizada.", "I>R>V"),
            ("A alteração necessária excede a autorização declarada.", "I>H"),
            ("A configuração já satisfaz as restrições declaradas.", "I>V"),
        ],
    },
}


def build() -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    tasks: list[dict] = []
    answers: dict[str, dict] = {}
    fixtures: dict[str, dict] = {}
    for family, specification in FAMILIES.items():
        for index in range(20):
            objective, expected = specification["cases"][index % len(specification["cases"])]
            task_id = f"{family}_{index + 1:02d}"
            actions = [
                {"code": code, "description": description}
                for code, description in specification["actions"].items()
            ]
            tasks.append(
                {
                    "id": task_id,
                    "family": family,
                    "source_domain": specification["source_domain"],
                    "target_domain": specification["target_domain"],
                    "objective": f"Caso {index + 1}: {objective} Qual sequência segura de ações deve ser usada?",
                    "response_format": "CÓDIGO>CÓDIGO(>CÓDIGO)",
                    "actions": actions,
                }
            )
            answers[task_id] = {"expected_sequence": expected}
            fixtures[task_id] = {"fixture_state": f"private_{family}_{index + 1:02d}", "contract_version": "transfer100-v1"}
    return tasks, answers, fixtures


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    tasks, answers, fixtures = build()
    if len(tasks) != 100 or len(answers) != 100 or len(fixtures) != 100:
        raise RuntimeError("Transfer-100 deve conter exatamente 100 tarefas, contratos e fixtures")
    (ROOT / "tasks.yaml").write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (ROOT / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "README.md").write_text(
        "# Transfer-100\n\nTarefas públicas, contratos e fixtures privados são mantidos separados. O corpus de experiências não pode conter objetivo, contrato ou fixture deste benchmark.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
