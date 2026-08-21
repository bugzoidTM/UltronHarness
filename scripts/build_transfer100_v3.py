"""Gera o Transfer-100 v3 público e seus contratos externos não versionáveis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

PUBLIC_ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "transfer100_v3"

FAMILIES: dict[str, dict[str, object]] = {
    "structured_validation": {
        "source_domain": "json_contracts",
        "target_domain": "yaml_service_manifests",
        "actions": {"P": "ler a entrada com parser permitido", "C": "validar campos, tipos e restrições declaradas", "R": "rejeitar e registrar a violação", "A": "aceitar a estrutura verificada"},
        "cases": [
            ("manifesto não pode ser analisado", "P>R"), ("campo service ausente", "P>C>R"), ("porta contém texto", "P>C>R"), ("lista de rotas possui duplicata", "P>C>R"),
            ("valor enum de ambiente é inválido", "P>C>R"), ("referência a segredo obrigatório está vazia", "P>C>R"), ("campo de versão viola o padrão", "P>C>R"), ("mapa de variáveis contém chave proibida", "P>C>R"),
            ("lista de dependências excede o limite", "P>C>R"), ("subdocumento de healthcheck é nulo", "P>C>R"), ("identificador contém caracteres não permitidos", "P>C>R"), ("intervalo de timeout está fora do contrato", "P>C>R"),
            ("porta duplicada em dois listeners", "P>C>R"), ("campo opcional possui tipo incompatível", "P>C>R"), ("referência interna aponta para serviço inexistente", "P>C>R"), ("política de reinício é desconhecida", "P>C>R"),
            ("manifesto possui todos os campos válidos", "P>C>A"), ("manifesto válido usa valores mínimos", "P>C>A"), ("manifesto válido contém configuração opcional", "P>C>A"), ("manifesto válido contém múltiplos listeners", "P>C>A"),
        ],
    },
    "dependency_recovery": {
        "source_domain": "python_lockfiles",
        "target_domain": "node_package_resolution",
        "actions": {"M": "inspecionar declaração e resolução", "I": "instalar o recurso declarado", "L": "reparar a resolução declarada", "V": "verificar a resolução final", "E": "registrar recurso não declarado e parar"},
        "cases": [
            ("pacote direto declarado está ausente", "M>I>V"), ("versão do pacote direto diverge do manifesto", "M>L>V"), ("pacote transitivo falta no lockfile", "M>L>V"), ("importação cita pacote não declarado", "M>E"),
            ("peer dependency exige versão incompatível", "M>L>V"), ("resolução aponta para checksum inválido", "M>L>V"), ("pacote opcional é usado sem declaração", "M>E"), ("registro local contém pacote declarado ausente", "M>I>V"),
            ("alias de pacote aponta para versão diferente", "M>L>V"), ("subdependência exige deduplicação", "M>L>V"), ("pacote declarado possui binário ausente", "M>I>V"), ("manifesto referencia escopo privado não declarado", "M>E"),
            ("lockfile omite dependência de produção", "M>L>V"), ("resolução marca pacote incompatível com plataforma", "M>L>V"), ("instalação foi interrompida antes do pacote declarado", "M>I>V"), ("importação transitiva não aparece na cadeia declarada", "M>E"),
            ("dependência declarada aponta para arquivo inexistente", "M>L>V"), ("pacote declarado foi removido do cache local", "M>I>V"), ("versão é válida mas a árvore não foi reconstruída", "M>L>V"), ("nome solicitado não existe em manifesto nem lockfile", "M>E"),
        ],
    },
    "state_recovery": {
        "source_domain": "filesystem_checkpoint_recovery",
        "target_domain": "repository_worktree_recovery",
        "actions": {"S": "inspecionar estado e escopo autorizados", "R": "reverter somente o delta autorizado", "V": "verificar o estado final", "N": "registrar que nenhuma alteração é necessária", "F": "registrar falha de verificação sem ampliar o escopo"},
        "cases": [
            ("um arquivo autorizado difere do checkpoint", "S>R>V"), ("arquivo já corresponde ao checkpoint", "S>N"), ("reversão autorizada ainda diverge após verificação", "S>R>F"), ("somente o arquivo de configuração está autorizado", "S>R>V"),
            ("índice contém mudança autorizada em um caminho", "S>R>V"), ("worktree possui mudança não autorizada e não deve ser tocada", "S>F"), ("arquivo removido autorizado deve ser restaurado", "S>R>V"), ("arquivo novo não pertence ao escopo de recuperação", "S>F"),
            ("checkpoint já contém a mesma alteração solicitada", "S>N"), ("renomeação autorizada não preservou o conteúdo", "S>R>V"), ("arquivo binário autorizado tem hash divergente", "S>R>V"), ("comparação falha por ausência de evidência de checkpoint", "S>F"),
            ("duas mudanças existem, mas apenas uma é recuperável", "S>R>V"), ("estado limpo confirma objetivo sem modificação", "S>N"), ("reversão expõe conflito não autorizado", "S>R>F"), ("metadado autorizado diverge do snapshot", "S>R>V"),
            ("permissão do arquivo diverge, conteúdo coincide", "S>R>V"), ("artefato temporário está fora da lista autorizada", "S>F"), ("reversão parcial deixa um hunk divergente", "S>R>F"), ("snapshot e worktree são equivalentes", "S>N"),
        ],
    },
    "planning": {
        "source_domain": "algorithm_dependency_graphs",
        "target_domain": "project_workflows",
        "actions": {"C": "confirmar evidência de pré-condição", "K": "manter dependente bloqueado", "E": "executar etapa habilitada", "V": "validar evidência de conclusão"},
        "cases": [
            ("build depende de teste ainda sem evidência", "C>K"), ("migração depende de backup que falhou", "C>K"), ("deploy depende de artefato assinado", "C>K"), ("etapa isolada está pronta para execução", "E>V"),
            ("duas pré-condições foram verificadas", "C>E>V"), ("aprovação manual ainda está pendente", "C>K"), ("geração de relatório não possui dependências", "E>V"), ("teste de integração passou e habilita empacotamento", "C>E>V"),
            ("artefato foi criado mas não validado", "C>K"), ("limpeza depende de retenção confirmada", "C>K"), ("sincronização independente exige validação final", "E>V"), ("lint e testes possuem evidências válidas", "C>E>V"),
            ("etapa posterior depende de contrato externo indisponível", "C>K"), ("verificação local habilita a próxima etapa", "C>E>V"), ("publicação exige versionamento ainda ausente", "C>K"), ("coleta de métricas pode executar imediatamente", "E>V"),
            ("dependência foi concluída mas sem artefato verificável", "C>K"), ("duas etapas predecessoras estão verificadas", "C>E>V"), ("arquivo de entrada não existe", "C>K"), ("validação de documentação pode executar sem bloqueios", "E>V"),
        ],
    },
    "configuration_repair": {
        "source_domain": "ini_configuration_repair",
        "target_domain": "service_runtime_configuration",
        "actions": {"I": "inspecionar estrutura e valores", "R": "aplicar reparação mínima autorizada", "V": "validar a configuração resultante", "H": "registrar que a mudança excede a autorização"},
        "cases": [
            ("chave obrigatória está ausente com valor autorizado", "I>R>V"), ("porta possui tipo inválido com correção autorizada", "I>R>V"), ("mudança exige alterar host fora do escopo", "I>H"), ("configuração já satisfaz o contrato", "I>V"),
            ("timeout nulo possui valor padrão autorizado", "I>R>V"), ("lista de origem permitida contém entrada inválida", "I>R>V"), ("alteração solicita remover política de segurança", "I>H"), ("modo de log já está conforme contrato", "I>V"),
            ("chave de ambiente tem espaço extra corrigível", "I>R>V"), ("limite de conexão é negativo e possui mínimo autorizado", "I>R>V"), ("reparo exige criar segredo inexistente", "I>H"), ("mapeamento de rota já é válido", "I>V"),
            ("nome de serviço possui caractere corrigível", "I>R>V"), ("formato de URL possui esquema ausente autorizado", "I>R>V"), ("correção exigiria trocar credencial", "I>H"), ("compressão já usa valor permitido", "I>V"),
            ("intervalo de retry tem valor vazio com padrão autorizado", "I>R>V"), ("diretório temporário possui separador corrigível", "I>R>V"), ("reparo solicita abrir acesso de rede", "I>H"), ("campo de versão já é compatível", "I>V"),
        ],
    },
}


def build() -> tuple[list[dict[str, object]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    tasks: list[dict[str, object]] = []
    answers: dict[str, dict[str, str]] = {}
    fixtures: dict[str, dict[str, str]] = {}
    for family, specification in FAMILIES.items():
        cases = specification["cases"]
        assert isinstance(cases, list) and len(cases) == 20
        seen = set()
        for index, (problem, expected) in enumerate(cases, start=1):
            if problem in seen:
                raise RuntimeError(f"Caso repetido em {family}: {problem}")
            seen.add(problem)
            task_id = f"{family}_v3_{index:02d}"
            actions = [{"code": code, "description": description} for code, description in dict(specification["actions"]).items()]
            tasks.append({"id": task_id, "family": family, "source_domain": specification["source_domain"], "target_domain": specification["target_domain"], "objective": f"Incidente: {problem}. Qual sequência segura de ações deve ser usada?", "response_format": "CÓDIGO>CÓDIGO(>CÓDIGO)", "actions": actions, "case_key": f"{family}:v3:{index:02d}"})
            answers[task_id] = {"expected_sequence": expected, "contract_version": "transfer100-v3"}
            fixtures[task_id] = {"fixture_state": f"external_{family}_{index:02d}", "contract_version": "transfer100-v3"}
    return tasks, answers, fixtures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=PUBLIC_ROOT)
    parser.add_argument("--contract-root", type=Path, required=True)
    args = parser.parse_args()
    tasks, answers, fixtures = build()
    if len(tasks) != 100 or len(answers) != 100 or len(fixtures) != 100:
        raise RuntimeError("Transfer-100 v3 deve conter 100 tarefas e contratos")
    args.public_root.mkdir(parents=True, exist_ok=True)
    args.contract_root.mkdir(parents=True, exist_ok=True)
    (args.public_root / "tasks.yaml").write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (args.public_root / "README.md").write_text("# Transfer-100 v3\n\nContém somente tarefas públicas. Contratos e fixtures são gerados em diretório externo informado por `--contract-root` e não devem ser versionados.\n", encoding="utf-8")
    (args.contract_root / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.contract_root / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
