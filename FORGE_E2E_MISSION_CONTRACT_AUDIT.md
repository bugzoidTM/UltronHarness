# Auditoria do contrato de missão — Forge E2E

## Achado

A revisão identificou que as missões públicas já declaravam `allowed_tools` e `action_budget`, mas esses campos não eram persistidos como parte da tarefa nem auditados no resultado E2E. O runner reduzia o `ToolRegistry` antes de criar o orquestrador, mas o contrato não era uma propriedade explícita da tarefa para o planejador, a política ou o limitador de ações.

A consequência metodológica é que os resultados anteriores comprovam apenas que o runtime executado não completou as missões. Eles não isolam de forma suficiente a capacidade de planejamento do `qwen2.5:3b`, pois a integridade do contrato por missão não havia sido demonstrada.

## Correção

O contrato de cada missão é agora transportado do YAML público para `TaskCreate`, persistido na tabela `tasks` e reidratado em toda leitura da tarefa. A persistência adiciona `allowed_tools_json`, `action_budget_min` e `action_budget_max` com migrações SQLite aditivas e compatíveis com bancos existentes.

| Camada | Controle aplicado |
|---|---|
| Runner Forge | Copia `allowed_tools` e `action_budget` da missão para `TaskCreate`. |
| Contexto da tarefa | Mantém o contrato após criação, reinicialização e recuperação. |
| Planner | Recebe somente a lista autorizada e o teto de ações no prompt. |
| Política de execução | Bloqueia uma ferramenta fora do contrato antes da decisão de risco e registra `mission_contract.tool_blocked`. |
| Limitador | Usa o menor valor entre o teto global e `action_budget.max`; o orçamento nunca amplia um limite de segurança global. |
| Auditoria E2E | Compara contrato da missão e tarefa, lista ferramentas solicitadas e registra teto respeitado. |

O limite inferior de `action_budget` é mantido como diagnóstico de trajetória, sem bloquear nem invalidar uma execução que conclua com menos chamadas. O teto é o controle operacional: ultrapassá-lo torna a medição inválida. Essa distinção evita transformar eficiência legítima em violação de segurança.

## Validação controlada

Uma missão pública foi executada com `ollama_research` (`qwen2.5:3b`) e seed `53`. A execução vinculou e preservou integralmente o contrato de ferramentas e orçamento. O único tool efetivamente solicitado foi `python.execute`, pertencente à allowlist. O teto de 12 chamadas foi respeitado e não houve aprovação artificial.

| Campo | Evidência |
|---|---:|
| Missão | `forge_e2e_01` |
| Ferramentas da missão e da tarefa | `[file.list, file.read, python.execute]` — idênticas |
| Orçamento da missão e da tarefa | `[5, 12]` — idêntico |
| Ferramentas efetivamente solicitadas | `python.execute` |
| Contrato de ferramentas respeitado | `true` |
| Teto de ações respeitado | `true` |
| Meta mínima diagnóstica atingida | `false` (1 de 5); não é um gate operacional |
| Modelo e seed atribuídos | `qwen2.5:3b`, seed `53`, em 2 chamadas |
| Reparo estruturado | Tentado; não validou `Plan` |
| Validade de medição | `false`, somente por `planner_not_structured_model_output` |

> A auditoria remove `allowed-tool contract` e `per-mission budget` da lista de lacunas de infraestrutura. O ATC `0,0` desta execução ainda não mede capacidade do modelo porque o plano foi criado pelo fallback após as duas tentativas estruturadas falharem. Não há promoção de autonomia, risco, verificadores, escopo de segurança ou experiência com base nesse resultado.

## Quality gates

A implementação foi validada com **97 testes aprovados**, cobertura de ramos de **77,86%** e lint sem violações. As regressões cobrem a persistência do contrato, sua exposição ao planejador, o bloqueio determinístico de ferramenta não autorizada, a manutenção do fluxo de aprovação padrão e o teto de ações por missão.
