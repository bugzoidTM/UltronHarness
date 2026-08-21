# Relatório de Testes e Cobertura — UltronPro

**Data da execução:** 20 de agosto de 2026  
**Escopo:** pacote `ultron`, com cobertura de ramos habilitada.  
**Ambiente:** Python 3.12.10, pytest 8.4.2, coverage 7.15.4 e pytest-cov 6.3.0.

## Resultado executivo

A suíte automatizada foi executada integralmente com provider determinístico local para que os testes de contrato não dependessem da latência variável de inferência generativa. O runtime de produção permanece configurado para Ollama com `qwen2.5:0.5b`; essa separação preserva testes rápidos, reproduzíveis e independentes de rede.

| Indicador | Resultado | Critério |
|---|---:|---:|
| Testes executados | 8 | — |
| Testes aprovados | 8 | Todos aprovados |
| Falhas | 0 | 0 |
| Cobertura total com ramos | **70,04%** | ≥ 70% |
| Lint estático | Aprovado | Sem erros |
| Relatório HTML | Gerado | `data/artifacts/coverage_html/` |
| Relatório JSON | Gerado | `data/artifacts/coverage.json` |

> A cobertura ultrapassou o limite configurado de 70%, incluindo análise de ramos, e por isso a verificação de qualidade foi concluída com sucesso.

## Escopo validado

A suíte cobre a inicialização do banco SQLite, criação e busca de memória híbrida, regras de isolamento de workspace, aprovação de escrita supervisionada, ciclo de tarefa, persistência de eventos, experiência aprendida e kill switch HTTP. Também foi testada a substituição controlada do provider do modelo por variável de ambiente, usada apenas no contexto automatizado.

| Área | Evidência principal |
|---|---|
| Persistência | Inicialização do esquema SQLite e leitura de entidades |
| Memória | Criação, ranking híbrido e recuperação de memória semântica |
| Política | Bloqueio de escape de workspace e aprovação de R2 em modo supervisionado |
| Orquestração | Criação, execução, estados, plano fallback e timeline de tarefa |
| Aprovações | Execução de ferramenta após decisão humana e conclusão da missão |
| Aprendizagem | Criação de experiência e memória vinculada à tarefa concluída |
| API | Health check, tarefas e parada global |
| Qualidade | Ruff executado sem erros funcionais |

## Reprodutibilidade

Para repetir a execução, use o ambiente virtual do projeto:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --cov=ultron --cov-branch --cov-report=term-missing --cov-report=html:data\artifacts\coverage_html --cov-report=json:data\artifacts\coverage.json
```

O limiar de qualidade é configurado em `pyproject.toml` através de `fail_under = 70`. Os relatórios detalhados permanecem locais e não transmitem telemetria para serviços externos.

## Observações técnicas

A cobertura atual é adequada ao limiar de qualidade do MVP, mas ainda há oportunidade de ampliar testes para caminhos de browser isolado, Qdrant, recuperação de falhas de ferramentas, política de rede e fluxos completos de experimentos. Esses componentes devem ser adicionados com cenários determinísticos antes de aumentar o limiar de cobertura em ciclos posteriores.
