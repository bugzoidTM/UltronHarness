# RELATÓRIO DE READINESS — GENERAL REASONING V1

**Projeto:** UltronHarness / Horizon  
**Escopo:** auditoria operacional pareada GR-1 versus GR-2  
**Data da coleta registrada:** 25 de agosto de 2026  
**Status científico:** validação de pipeline concluída; coleta confirmatória unseen ainda bloqueada

## 1. ESCOPO E INTERPRETAÇÃO

Este relatório registra a prontidão operacional observada na calibração e na validação privadas do benchmark General Reasoning v1. A comparação foi executada no mesmo modelo-base efetivo, com a mesma seed, o mesmo split, a mesma lista de modos e a mesma orientação por missão. A variante GR-1 manteve o estado epistêmico ativo e `prediction_before_observation=false`; a variante GR-2 manteve o estado epistêmico ativo e `prediction_before_observation=true`.

A finalidade desta etapa foi verificar o pipeline experimental — atribuição de modelo, seed, contrato, orientação compartilhada, isolamento de fixture, allowlist, limite de ações, temporalidade e completude das previsões — e não estimar ganho de capacidade. A calibração e a validação não autorizam qualquer declaração de generalização, lift ou superioridade do GR-2.

> **Regra de interpretação:** `measurement_valid=true` significa que o trace satisfaz os gates instrumentais avaliados pelo runner. Não significa que a missão passou no evaluator nem que a hipótese científica foi confirmada.

## 2. IDENTIDADE CONGELADA OBSERVADA

A coleta de validação utilizou o alias `ollama`, resolvido para o modelo efetivo `qwen2.5:0.5b`, seed 53, modo `full_plan`, split `validation` e o commit `4ebbe788cdf6f6146142740e7a9366923720c0b5`. O hash do caminho de tarefas registrado nos dois artefatos foi `2c56fca565472584907fc46dd2db971787e2e982cebb626efe77a7cce2b76f34`. O hash do evaluator privado registrado foi o mesmo nos dois lados: `44b7d7f676ed7df27997518a7996733b4856bcc834fcacf0719dabc65155f414`.

| Dimensão | GR-1 control | GR-2 candidate | Gate de paridade |
|---|---|---|---|
| Alias do modelo | `ollama` | `ollama` | Igual |
| Modelo efetivo | `qwen2.5:0.5b` | `qwen2.5:0.5b` | Igual |
| Seed | 53 | 53 | Igual |
| Split | `validation` | `validation` | Igual |
| Modo | `full_plan` | `full_plan` | Igual |
| Flag GR-2 | Desligada | Ligada | Diferenciação declarada |
| Hash do caminho de tarefas | Igual | Igual | Igual |
| Hash do evaluator privado | Igual | Igual | Igual |
| Hash do contrato de missão registrado | Igual | Igual | Igual |
| Traces | 40 | 40 | Completo |
| `measurement_valid` | `true` | `true` | Passou |

## 3. GATES OPERACIONAIS DA VALIDAÇÃO

Os dois artefatos de validação não registraram razões de invalidação. Em todos os 40 traces de cada variante, a atribuição do modelo, a atribuição da seed, a verificação do contrato de missão, a orientação compartilhada, o respeito à allowlist e o limite superior do orçamento foram marcados como verificados. Não foram detectadas chamadas de ferramenta antes da primeira decisão do modelo, não houve erro do evaluator e os hashes do fixture inicial coincidiram com o fixture de referência em todos os traces.

| Gate sanitizado | GR-1 | GR-2 | Interpretação |
|---|---:|---:|---|
| Atribuição de modelo verificada em todos os traces | Sim | Sim | Sem mistura de modelos |
| Atribuição de seed verificada em todos os traces | Sim | Sim | Paridade de seed preservada |
| Contrato de missão verificado em todos os traces | Sim | Sim | Allowlist e budget conferidos |
| Orientação compartilhada verificada em todos os traces | Sim | Sim | Shared orientation preservada |
| Allowlist respeitada em todos os traces | Sim | Sim | Sem ferramenta fora do contrato |
| Teto de ações respeitado em todos os traces | Sim | Sim | Sem extrapolação do budget |
| Pre-decision tool call | 0 | 0 | Nenhuma ocorrência detectada |
| Erros do evaluator | 0 | 0 | Nenhum erro registrado |
| Fixture inicial igual ao de referência | Sim | Sim | Isolamento inicial verificado |
| Previsões pendentes | 0 | 0 | Nenhuma pendência terminal registrada |

Na variante GR-1 foram registrados zero pares de previsão, como esperado para a flag desligada. Na variante GR-2 foram registrados 260 pares de previsão e 260 observações correspondentes, sem previsão pendente. Esse resultado confirma a integridade estrutural da sequência de previsão e observação no trace; não substitui o rótulo independente de acerto previsto no protocolo científico.

## 4. CALIBRAÇÃO

A calibração privada foi executada em duas missões, com seed 53 e modo `full_plan`. GR-1 e GR-2 produziram dois traces cada, ambos com `measurement_valid=true` e sem razão de invalidação. Esses artefatos são exclusivamente de readiness. Nenhuma métrica de calibração foi usada para selecionar famílias, missões, prompts, thresholds, orçamento, seeds ou método estatístico da etapa confirmatória.

## 5. LIMITAÇÕES E BLOQUEIOS ANTES DO UNSSEEN

A validação passou nos gates que o runner atual consegue verificar, mas não encerra a prontidão científica completa. O runner ainda precisa ser endurecido antes da abertura confirmatória: a ordem das variantes deve ser randomizada e registrada por seed; o manifesto final deve conter hashes explícitos do protocolo, contratos, evaluator e política de leakage; a coleta deve possuir retomada/checkpoint seguro; e deve ser exportado um resultado pareado sanitizado por missão-seed.

Também permanece bloqueada a reivindicação de `prediction accuracy` científica independente. O campo atualmente disponível no artefato é uma métrica instrumental baseada na verificação interna da previsão. O protocolo exige que o evaluator privado ou um pós-processador privado produza o rótulo independente comparando expectativa, observação real e outcome final, sem usar a classificação interna como única fonte.

Há ainda um bloqueio de isolamento estrito: a lógica temporária de geração de contratos privados esteve presente no repositório público durante a preparação inicial. Antes de qualquer coleta unseen, esse gerador deve ser removido ou deslocado para um fluxo exclusivamente privado, e os contratos unseen devem ser rotacionados ou reconstruídos sob controle privado. Enquanto essa correção não for concluída e auditada, os contratos atuais não devem ser tratados como unseen confirmatório.

Por fim, a validação utilizou um único seed e serve apenas à auditoria de execução. O protocolo confirmatório continua exigindo múltiplas seeds, famílias primárias inéditas, análise agrupada por família, intervalo de confiança de 95%, teste pareado e auditoria de leakage. Não é permitido iniciar o unseen para produzir um resultado positivo por extrapolação da validação.

## 6. DECISÃO DE READINESS

| Item | Estado | Decisão |
|---|---|---|
| Implementação GR-2 atrás de flag independente | Passou | Manter ativação explícita por variante |
| Calibração privada | Passou como readiness | Não usar como evidência científica |
| Validação privada | Passou nos gates instrumentais | Não usar como evidência de lift |
| Modelo confirmatório | Fixado na coleta atual | Revalidar no freeze confirmatório |
| Identidade pareada básica | Passou | Preservar hashes e seed |
| Leakage audit completo por execução | Pendente | Bloqueia unseen |
| Isolamento estrito do gerador privado | Pendente | Bloqueia unseen |
| Runner pareado com retomada e exportação sanitizada | Parcial | Bloqueia unseen |
| Rótulo independente de prediction accuracy | Pendente | Bloqueia métrica secundária e promoção |
| Coleta unseen | **Fechada** | Não iniciar nesta fase |

**Conclusão:** a calibração e a validação demonstram que o pipeline atual consegue executar pares GR-1/GR-2 no modelo e seed previstos sem registrar violações nos gates instrumentais disponíveis. A prontidão científica confirmatória permanece **bloqueada** até a restauração do isolamento estrito, o endurecimento do runner, a auditoria de leakage e o freeze final. Nenhuma conclusão sobre generalização ou ganho do GR-2 é autorizada neste relatório.

## 7. ARTEFATOS SANITIZADOS DE REFERÊNCIA

A calibração está registrada no manifesto `collection_20260825T130333Z`; a validação está registrada no manifesto `collection_20260825T161017Z`. Este relatório não inclui contratos, respostas esperadas, fixtures, entradas do evaluator, detalhes privados de avaliação ou conteúdo de ouro.
