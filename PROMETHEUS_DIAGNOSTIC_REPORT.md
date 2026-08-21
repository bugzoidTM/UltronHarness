# Project Prometheus — Relatório do Ciclo de Diagnóstico Cognitivo

## Conclusão executiva

O UltronPro concluiu o ciclo de diagnóstico previsto no PRD v0.3 e atingiu o marco **CG-1** sob protocolo controlado. A configuração vencedora mantém o benchmark UGIB-Lite 0.2 com 50 tarefas, a seed propagada ao runtime local, pontuação automática e corpus de experiências separado das tarefas e respostas privadas do benchmark.

> **CG-1 atingido:** três execuções independentes com `qwen2.5:3b`, fresh versus experienced, obtiveram `mean(CGFE) = +0,02`.

O resultado não constitui alegação de inteligência geral. Ele mostra, somente nesta configuração local e família de benchmark, que experiências procedurais curtas, filtradas pela categoria da tarefa, elevaram o desempenho médio em casos inéditos mensurados automaticamente.

## Protocolo CGFE-2 aprovado

| Condição | Valor |
|---|---:|
| Modelo de pesquisa | `qwen2.5:3b` via Ollama local |
| Benchmark | UGIB-Lite 0.2 |
| Tarefas | 50: 10 reasoning, 15 coding, 15 tool use, 10 recovery |
| Seeds independentes | 42, 43 e 44 |
| Fresh médio | 0,70 |
| Experienced médio | 0,72 |
| Mean CGFE | **+0,02** |
| Mediana CGFE | +0,02 |
| Mínimo / máximo | 0,00 / +0,04 |
| IC95% do CGFE | -0,0026 a +0,0426 |

O intervalo de confiança ainda cruza zero porque há somente três execuções e a diferença é pequena. Portanto, CG-1 é atingido pelo critério inicial definido no PRD — média positiva em ao menos três execuções — mas o efeito deve ser reproduzido com mais seeds antes de qualquer afirmação forte. O marco CG-2, de crescimento comprovado com a quantidade de experiências, continua aberto.

## Diagnósticos e decisão mínima

| Família | Observação mensurada | Decisão |
|---|---|---|
| MEM-1 | No modelo de 0,5B, top-k 0 obteve 0,40 e todos os níveis de 1 a 10 memórias degradaram o score. | Não injetar memória genérica indiscriminadamente. |
| MEM-2 | Nenhum tipo de memória melhorou a condição NONE no modelo de 0,5B. | Priorizar filtro por relevância e não quantidade de memória. |
| MEM-3 | MEM-EVAL com 30 queries rotuladas registrou Precision@K médio de 0,4222 e identificou `mem_bad_recipe` como prejudicial. | Persistir candidate trace e separar relevância de utilidade empírica. |
| CTX-1/CTX-2 | FULL = 0,40; NO_SKILLS = 0,45; MINIMAL = 0,35 no modelo de 0,5B. | Não incluir bloco de skills quando ele não é relevante à tarefa. |
| ORCH-1 | TOOLS_DIRECT = 0,55; ORCH_FULL = 0,25 no modelo de 0,5B. | Complexidade de orquestração não é promovida sem benefício medido. |
| MODEL-1 | `qwen2.5:0.5b` teve limite prático; `qwen2.5:3b` permitiu CGFE médio positivo após filtragem. | `qwen2.5:0.5b` é smoke model; `qwen2.5:3b` é research primary. |
| SEED-1 anterior | A configuração não filtrada produziu resultado instável/negativo em UGIB-50. | A hipótese de interferência de contexto foi aceita e a configuração foi corrigida. |
| LEARN-1 anterior | A curva com corpus genérico manteve CGFE -0,02. | Não consolidar experiências genéricas sem filtro de categoria. |

## Mudança causalmente motivada

A mudança mantida não adiciona arquitetura estética. O runner passou a aceitar experiências etiquetadas por categoria (`reasoning`, `coding`, `tool_use`, `recovery`) e a injetar somente as entradas da categoria da tarefa. Quando não há entrada aplicável, os prompts fresh e experienced permanecem semanticamente equivalentes. O corpus contém princípios procedurais, não IDs, objetivos, fixtures, gabaritos ou testes ocultos do UGIB.

Essa alteração foi motivada por MEM-1, MEM-2 e CTX-2: o contexto genérico degradava modelos pequenos, enquanto a configuração com um modelo de pesquisa mais capaz e recuperação relevante por categoria mostrou ganho médio positivo. Todos os runs — inclusive os negativos — continuam preservados em `data/artifacts/` e no banco local.

## Integridade, segurança e qualidade

| Gate | Resultado |
|---|---|
| Testes determinísticos | 24 aprovados |
| Cobertura com branches | 71% (limiar 70%) |
| Lint | aprovado |
| Segurança Windows | 12 aprovados, 1 skipped por limitação de symlink do ambiente |
| Testes cognitivos reais | 9 aprovados, 1 xfailed esperado |
| Build React | aprovado |
| Smoke API/UI | aprovado |
| Política de resultados negativos | append-only; ativa |
| Auditoria de `UltronLocal` | nenhum código incorporado; repositório sem licença declarada |

## Reproduzir o marco

```powershell
# O modelo deve aparecer em `ollama list`.
.\.venv\Scripts\python.exe -m ultron.benchmarks multi-seed `
  --model ollama_research --seeds 42 43 44 --experiences 50
```

Os manifests registram modelo, seed, configuração e ambiente. A interface local apresenta os novos runs na seção **Research → Diagnostics**, e a API agregada permanece disponível em `GET /api/research/dashboard`.

## Próximas hipóteses científicas

O próximo passo não é autoedição. Recomenda-se ampliar SEED-1 para dez seeds com a configuração filtrada, repetir LEARN-1 usando somente experiências por categoria e medir transferência para um conjunto relacionado, mas não visto. Só após estabilidade estatística e utilidade de memória mensurável deve-se considerar qualquer alteração mais profunda no Learning Engine.
