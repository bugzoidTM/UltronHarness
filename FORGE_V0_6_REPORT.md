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
| `FORGE-4` | **NÃO APROVADO** | As amostras reais E2E tiveram `ATC = 0`; o avaliador privado permaneceu a fonte exclusiva de sucesso. |
| `FORGE-5` | **NÃO APROVADO** | Não houve missão com falha recuperada e aprovada pelo avaliador privado. |
| `E2E-LEARN-1` / `FORGE-6` | **NÃO MEDIDO** | A comparação Fresh versus Experienced foi implementada como infraestrutura de replay, mas não executada após `FORGE-4` permanecer negativo. |

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
| E2E Generative | `qwen2.5:3b`, 1 missão por tentativa | `ATC = 0,0`; o planejador local excedeu o orçamento ou caiu no fallback e solicitou aprovação para escrita. |

A avaliação E2E negativa é preservada como resultado válido. O principal gargalo atual é o planejamento estruturado pelo modelo local de 3B para missões de arquivo, e não falta de telemetria, de verificador ou de módulo cognitivo adicional.

## Quality gates

| Gate | Resultado |
|---|---:|
| Testes determinísticos | **91 passed** |
| Cobertura branch | **79,06%** |
| Segurança Windows | **12 passed, 1 skipped** |
| Testes de agente | **9 passed, 1 xfailed** |
| Ruff | **PASS** |
| Build React/Vite | **PASS** |
| Smoke API/UI | **PASS** |
| CI | Workflow Forge preparado no workspace local; sua publicação requer credencial GitHub com permissão `workflows`. |

## Próximo gargalo verificável

A próxima iteração deve melhorar somente o planejamento estruturado local e a execução E2E sob aprovação explícita, preservando os contratos privados e o frozen Target. Nenhuma família deve ser promovida ao runtime até que Calibration gere evidência pareada positiva e Target apresente ganho seletivo com intervalo de confiança positivo.
