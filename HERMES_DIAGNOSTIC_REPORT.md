# HERMES_DIAGNOSTIC_REPORT

## Resultado executivo

O Transfer-100 foi executado com o protocolo `transfer100-v2-batched`, modelo `ollama_research` e seeds solicitadas `[42, 43, 44, 45, 46, 47, 48, 49, 50, 51]`. O checkpoint está em estado **completed**, com **10/10** seeds concluídas.

| Métrica | Valor |
|---|---:|
| Transfer Gain médio | -0.0500 |
| IC95% | [-0.0500, -0.0500] |
| Seeds concluídas | 10 |
| Decisão Hermes Gate 1 | **SHADOW_REJECTED** |

A regra de promoção exige rodada completa, ganho médio positivo e limite inferior do IC95% estritamente positivo. Portanto, a decisão acima é mecânica e não usa avaliação por modelo.

## Resultado por família

| Família | Ganho médio por seed | N |
|---|---:|---:|
| configuration_repair | +0.0000 | 10 |
| dependency_recovery | +0.0000 | 10 |
| planning | +0.5000 | 10 |
| state_recovery | +0.0000 | 10 |
| structured_validation | -0.7500 | 10 |

## Decisões de produto

O roteador de experiências permanece em **shadow/experimental**. Ações `USE` não são integradas ao contexto ativo; `ABSTAIN` continua o comportamento padrão sob evidência insuficiente, e o firewall bloqueia famílias nocivas quando houver pares persistidos. A Symbolic Lane permanece isolada apesar de passar no Symbolic-100; World Model, Critic e Strategy Policy seguem observacionais.

## Reprodutibilidade e limites

Os contratos de avaliação permanecem privados; o corpus público não recebe gabaritos. Resultados negativos são preservados no checkpoint Transfer-100. Transferências cross-domain e cross-model só podem ser iniciadas após o Gate 1, para evitar que um resultado externo seja usado para compensar uma falha intrafamília.

## Quality gates

| Gate | Estado conhecido |
|---|---|
| Pytest determinístico + cobertura | PASS — 63 testes, 75,90% |
| Segurança Windows | PASS — 12 passed, 1 skipped |
| Testes de agente | PASS — 9 passed, 1 xfailed |
| Ruff | PASS |
| Build React | PASS |
| Smoke API/UI | PASS — missão supervisionada, aprovação, memória persistida e UI local |
