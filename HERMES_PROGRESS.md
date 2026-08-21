# Project Hermes — Checkpoint de Progresso

## Transfer-100

O benchmark `transfer100-v2-batched` foi criado com 100 tarefas públicas, contratos e fixtures privados isolados. A execução local multi-seed está ativa em segundo plano, com checkpoint persistido após cada seed. Os resultados parciais não são usados para promover qualquer roteamento até que as dez seeds comparáveis sejam concluídas.

## Assinaturas e roteamento seletivo

Foram implementadas assinaturas determinísticas de tarefa e experiência, compatibilidade estruturada, Expected Experience Utility baseada em deltas pareados e o roteador `USE / ABSTAIN / REJECT`. O roteador permanece experimental; `ABSTAIN` é o padrão sob incerteza, pouca evidência ou utilidade próxima de zero.

## Transferência negativa, destilação e skills

O firewall de transferência negativa persiste utilidade por par de famílias e bloqueia combinações classificadas como nocivas mesmo se houver similaridade. A destilação exige três experiências verificadas, compatíveis, de utilidade positiva e proveniência completa. Skills passaram a ter estado por família, sem promoção global.

## Symbolic-100

O benchmark determinístico Symbolic-100 passou com **100/100**, acurácia de **100%**, taxa de falsos positivos de **0%** e nenhuma execução insegura. Isto satisfaz o gate técnico de elegibilidade, mas a lane permanece em **shadow mode** até que sua telemetria representativa seja consolidada no ciclo Hermes.

## WORLD-100

O WORLD-100 foi executado sobre 100 outcomes reais dos artefatos Transfer-100 já persistidos. O resultado foi acurácia **0,810**, Brier **0,122109**, baseline de maioria **0,127500** e erro de calibração **0,079055**. A condição inicial `Brier(model) < Brier(baseline)` foi observada nesta amostra, mas ainda não é reprodutível em múltiplos conjuntos; o World Model continua somente em **shadow mode** e não altera ranking nem bloqueia ações.

## Cross-domain e cross-model

Os harnesses de generalização cross-domain e da matriz cross-model foram implementados e testados. A execução com modelo adicional permanece **deferred**: o checkpoint Transfer-100 atual apresenta quatro seeds comparáveis com TG médio de **-0,050**, abaixo do Hermes Gate 1. Nenhum corpus foi ajustado para outro modelo e nenhum teste cross-domain será usado para compensar esse resultado intrafamília negativo.

## Quality gates em andamento

A suíte determinística Hermes passou com **63 testes**, cobertura de **75,90%** e threshold de 70% atingido. O lint passou, o build React passou e os testes Windows/agent anteriores permaneceram aprovados. O smoke test deve ser repetido após a rodada Transfer-100, pois o runtime de modelo local estava ocupado e excedeu a janela curta de polling do smoke durante uma inferência concorrente.

A consolidação científica, a decisão Hermes Gate 1 e qualquer promoção continuam pendentes das seeds 49–51; resultados parciais negativos são preservados no checkpoint e não serão reclassificados por intervenção manual.

## Consolidação final do Transfer-100

A rodada Transfer-100 foi concluída em **10/10 seeds (42–51)**. O Transfer Gain foi invariável e negativo: média **-0,0500**, IC95% **[-0,0500, -0,0500]**, com fresh **0,1500** e experienced **0,1000** por seed. O **Hermes Gate 1 falhou**. A decisão é `SHADOW_REJECTED`: nenhum roteamento seletivo é promovido; o fallback permanece fresh-only/ABSTAIN e o firewall de transferência negativa continua ativo.

A distribuição por família revelou planning positiva (+0,5000) mas structured_validation fortemente negativa (-0,7500), com as demais famílias neutras. Essa heterogeneidade não é evidência de transferência geral e não autoriza promoção por família sem pares individuais persistidos e IC apropriado.

## Quality gates finais

| Gate | Resultado |
|---|---|
| Pytest determinístico + branch coverage | PASS — 63 passed, 75,90% |
| Segurança Windows | PASS — 12 passed, 1 skipped |
| Testes de agente | PASS — 9 passed, 1 xfailed |
| Ruff | PASS |
| Build React | PASS |
| Smoke API/UI | PASS — missão supervisionada, aprovação, memória persistida e UI local |

O produto local está funcional. A alegação científica permanece estritamente limitada: Hermes implementa seleção e rejeição auditáveis, mas **não demonstrou Transfer Gain geral positivo** neste Transfer-100; portanto, seus módulos continuam em shadow/experimental.
