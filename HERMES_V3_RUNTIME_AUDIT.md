# Auditoria Hermes v3 e Convergência Research–Runtime

## Diagnóstico confirmado

O resultado negativo do Transfer-100 v2 não deve ser interpretado como uma refutação geral da aprendizagem do UltronPro. O protocolo mede apenas `fresh` versus um contexto experiente injetado por família; ele não executa a política `USE / ABSTAIN / REJECT` que foi construída no Hermes. Além disso, o gerador atual expande quatro templates por família, os contratos privados estão no mesmo diretório versionável do benchmark e a condição batched substitui a execução por tarefa por um formato JSON agregado. Logo, o resultado é preservado como evidência contra **essa configuração experimental**, mas não valida nem invalida o roteador de utilidade.

| Limite atual | Evidência no código | Correção exigida |
|---|---|---|
| Repetição de tarefas | O gerador Transfer-100 recicla quatro casos por família | V3 com 20 casos distintos por família, problemas e ações independentes |
| Contratos não realmente ocultos | `answers.json` e `fixtures.json` residem em `benchmarks/transfer100/` | Contratos em diretório externo configurável e ignorado pelo Git |
| Mistura de protocolos | `batch_by_family` altera prompt, parser e unidade de decisão | Comparação explícita per-task versus batched, sem agregá-las na mesma conclusão |
| Família de recuperação defeituosa | `state_recovery` não expressa transição de estado suficientemente distinta | Novos contratos de pré-condição, rollback e verificação de estado |
| Gate incompleto | Mede `fresh` e `experienced`, não o roteador | Quatro braços: never inject, always inject, router USE/ABSTAIN/REJECT e oracle de contrato para diagnóstico |
| Runtime desconectado | O orquestrador usa apenas `MemoryService.search()` | `TaskSignature → ShadowExperienceRoutingService → ContextBuilder → _make_plan` |
| Replanejamento nominal | `_replan()` persiste reflexão e retorna `False` | Revisão de plano persistida, continuação limitada e causalmente vinculada à falha |
| Aprovação encerra a tarefa | `decide_approval()` marca `COMPLETED` após uma ferramenta | Retomar cursor do plano, verificar a etapa e continuar as próximas etapas |
| Verificação insuficiente | `success_condition` é texto sem avaliador | Verificadores determinísticos para arquivos, conteúdo, comandos e predicados de etapa |

## Ordem de implementação

A primeira alteração é o Transfer-100 v3 per-task, com contratos mantidos fora do repositório e um runner comparativo que registra cada tarefa, contexto efetivamente injetado, decisão do roteador e resultado determinístico. Em seguida, o runtime receberá um `ContextBuilder` observável: por padrão o roteador apenas registra; a injeção real só será permitida para famílias declaradas como aprovadas pela tabela de utilidade e pela configuração experimental.

O agente será corrigido antes de quaisquer módulos cognitivos novos. Aprovação não poderá significar conclusão; ela deverá retomar o plano salvo. Uma falha recuperável deverá produzir uma revisão de plano, salvar a nova revisão e continuar dentro dos limites de replanejamento. O verificador será a fonte de verdade para as condições de sucesso.

O benchmark final desta etapa será end-to-end e local: cada cenário terá um projeto de arquivos, uma falha inicial intencional, 10–30 passos permitidos, ações verificáveis, uma recuperação necessária e um contrato final privado. O sucesso não será inferido por texto do modelo, mas por verificadores de filesystem, conteúdo, estado e sequência de operações.

## Gates desta etapa

| Gate | Critério |
|---|---|
| V3-isolation | Nenhum contrato privado ou fixture de resposta no repositório público |
| V3-protocol | Per-task e batched registrados separadamente; decisão científica baseada em per-task |
| Router-AB | `Never`, `Always` e `Router` comparados em seeds pareadas por tarefa |
| Runtime-reuse | Cada contexto injetado tem assinatura, decisão, origem e evidência persistidas |
| Approval-continuity | A aprovação retoma o cursor e não conclui a tarefa antecipadamente |
| Replan-real | Falha recuperável cria revisão superior e executa passos de substituição |
| Verifier | Nenhuma tarefa end-to-end é concluída sem predicado determinístico satisfeito |
| E2E-long | Cenários reais de 10–30 passos completam recuperação, verificação e aprendizagem entre tarefas |
