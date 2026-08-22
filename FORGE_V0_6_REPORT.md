# Project Forge v0.6 — Relatório de implementação e evidências

## Síntese executiva

O Project Forge v0.6 foi implementado como uma convergência entre o plano de pesquisa e o runtime local do UltronPro. O ciclo introduz uma fronteira verificável entre datasets públicos e contratos privados, executa utilidade pareada somente em Calibration, congela o estado do roteador antes de Target, amplia a recuperação de candidatos, persiste continuações através de reinicializações e estabelece um benchmark E2E generativo com avaliador privado externo.

> **Decisão científica atual:** os gates de integridade, segurança e runtime foram aprovados. Não há evidência positiva para promover o Router ou declarar ganho E2E. O estado seguro permanece **ABSTAIN / fresh-only**.

| Dimensão | Estado | Evidência |
|---|---:|---|
| `PRIVACY-1` | **APROVADO** | Scanner encontrou `public_private_overlap = 0` em 88 arquivos públicos e 203 marcadores privados. |
| Splits Calibration/Target | **APROVADO** | 100 tarefas em cada split; Target com 30% canônica, 40% parafraseada e 30% adversarial. |
| Snapshot Router / Target congelado | **APROVADO** | O smoke Target confirmou hashes idênticos antes/depois e não gravou utilidade no Target. |
| `RETRIEVAL-1` | **APROVADO em diagnóstico controlado** | O candidato útil conhecido permaneceu no prefilter e o orçamento de matching foi limitado a 10. |
| `TASKSIG-200` | **APROVADO** | 200 casos determinísticos; 160 conhecidos e 40 fora de distribuição, com gate de abstinência satisfeito. |
| `CONTINUITY-1` | **APROVADO** | Continuação persistida em SQLite antes da pausa; destroy/recreate do orquestrador, aprovação e retomada verificados. |
| `FORGE-4` | **NÃO ELEGÍVEL PARA INTERPRETAÇÃO** | A amostra anterior usou `qwen2.5:0.5b`; a reexecução com 3B comprovado caiu em fallback por erro de JSON. Em ambos os casos, `ATC = 0` não mede a capacidade do planejador estruturado de 3B. |
| `FORGE-5` | **NÃO MEDIDO** | Não houve missão E2E válida, com plano estruturado do modelo, que falhasse e fosse recuperada. |
| `E2E-LEARN-1` / `FORGE-6` | **NÃO MEDIDO** | A comparação Fresh versus Experienced permanece bloqueada até uma medição E2E elegível. |

## Implementação entregue

### Privacidade e reprodutibilidade

O Transfer-100 v4 passou a usar `ULTRON_PRIVATE_BENCHMARK_ROOT` ou `research.private_benchmark_root`. Tarefas, schemas e loaders ficam em `benchmarks/transfer100_v4/`; respostas, fixtures e avaliadores são mantidos somente em `UltronHarness_private`. Runners falham de modo explícito sem a raiz privada. O scanner `ultron/research/leakage.py` não publica o texto dos contratos: ele informa apenas hashes de marcadores eventualmente encontrados.

Foram criados os splits públicos `benchmarks/forge_router_v1/calibration/` e `target/`, com domínios, identificadores e `case_key` independentes. A tabela `experience_pair_utility` recebeu contexto de família, domínios, seed, modelo, versão de prompt e split. O recálculo do firewall usa apenas dados de `calibration` ou legado; Target não pode promover famílias.

### Router Learning e recuperação

O snapshot Forge registra mapa de utilidade, thresholds, experiências elegíveis, hash da tabela de utilidade e hash do corpus. A avaliação Target executa Never Inject, Always Inject e Router em ordem randomizada por seed; ela compara os hashes antes/depois e gera erro se algum dado de Calibration for alterado.

O `ContextBuilder` agora aplica assinatura, prefilter SQL de até 50 candidatos, deduplicação por família e hash de procedimento, ranking de compatibilidade, limite de 10 candidatos em matching e limite de duas injeções. A Task Signature v2 possui família fechada, metadados públicos prioritários, heurística determinística, fallback JSON estruturado apenas para `unknown` e abstinência com confiança abaixo de 0,75.

### Runtime confiável

A tabela `task_continuations` persiste a revisão de plano, a etapa pendente, o contexto roteado, memória, ações e erros antes de `WAITING_APPROVAL`. A API recupera continuações pendentes durante sua inicialização sem reaplicar ações. Após uma aprovação, o orquestrador reconstrói o plano e o contexto de SQLite, executa a ação autorizada e retoma a sequência.

O `StepSuccessVerifier` foi transformado em registry fechado. São aceitos somente predicados registrados: resultado de ferramenta, dependência prévia, contexto de tarefa, existência e conteúdo de arquivo, schema JSON, manifesto de arquivos e comando previamente registrado. Shell livre não é aceito como condição de sucesso. Os rastros persistidos em `execution_traces` incluem revisão de plano, etapa, evidência e decisões de roteamento.

### E2E generativo e replay

O Forge E2E v1 contém dez missões públicas com orçamento de 5 a 20 ações e avaliadores privados externos. O runner usa o `Orchestrator` real, não altera `_make_plan` ou `_execute_plan`, registra `planner_source`, contabiliza aprovações e usa apenas o avaliador privado para `ATC`. A infraestrutura de replay aceita exclusivamente experiências verificadas, generaliza caminhos e linhas específicas e calcula ACG por séries pareadas, sem converter resultado nulo em ganho.

## Resultados experimentais locais

| Experimento | Configuração | Resultado |
|---|---|---|
| Calibration Forge (smoke) | `qwen2.5:3b`, seed 42, 5 pares | `mean_delta = 0,0`; utilidade registrada, nenhuma promoção. |
| Target Forge (smoke) | `qwen2.5:3b`, seed 42, 5 tarefas | Never/Always/Router = `0,0`; freeze proof aprovado. |
| E2E Generative original | Parâmetro `ollama_research`; modelo efetivo auditado | O registro `model_calls` mostrou `qwen2.5:0.5b`; o resultado não pode ser atribuído ao 3B. |
| E2E Generative retificado | `qwen2.5:3b`, seed 48, 1 missão | Atribuição verificada, mas `planner_source = fallback_after_model_error`; `measurement_valid = false` e `ATC = 0,0` não é interpretável como capacidade do 3B. |
| E2E com reparo estruturado | `qwen2.5:3b`, seed 50, 1 missão | Duas chamadas auditadas (`planning` + `planning_repair`), ambas com modelo e seed verificados; o reparo não validou `Plan`, portanto `measurement_valid = false`. Sem aprovação artificial no protocolo E2E. |

A avaliação E2E anterior foi **retificada**. A nova instrumentação fixa o alias solicitado na cópia isolada da configuração do runner, propaga a seed para planejamento e replanejamento, registra modelo/seed configurados e efetivos por missão e torna a medição inelegível quando o plano não provém de JSON estruturado do modelo. O próximo gargalo verificável é a confiabilidade do planejamento JSON do 3B, não uma alegada incapacidade E2E.

A execução de validação com seed `49` confirmou `effective_seed = 49` e `seed_attribution_verified = true` em `model_calls`. A validação subsequente com seed `50` confirmou que o mecanismo `structured()` foi efetivamente acionado: houve `planning` e `planning_repair`, ambos registrados com `qwen2.5:3b` e seed `50`. O segundo retorno ainda não satisfez o schema `Plan`; por isso, `planner_source = fallback_after_model_error` e a medida permanece inelegível. Nenhuma consolidação multi-seed deve ocorrer enquanto uma missão não registrar simultaneamente modelo efetivo correto, seed efetiva correta e `planner_source = model_structured`.

## Quality gates

| Gate | Resultado |
|---|---:|
| Testes determinísticos | **95 passed** |
| Cobertura branch | **77,97%** |
| Segurança Windows | **12 passed, 1 skipped** |
| Testes de agente | **9 passed, 1 xfailed** |
| Ruff | **PASS** |
| Build React/Vite | **PASS** |
| Smoke API/UI | **PASS** |
| CI | Workflow `.github/workflows/forge-ci.yml` criado; não executa benchmarks LLM pesados. |

## Próximo gargalo verificável

A próxima iteração deve melhorar somente o planejamento estruturado local e a execução E2E sob aprovação explícita, preservando os contratos privados e o frozen Target. Nenhuma família deve ser promovida ao runtime até que Calibration gere evidência pareada positiva e Target apresente ganho seletivo com intervalo de confiança positivo.
