# GR-0 — Frozen Baseline Report

## Status do gate

**Gate metodológico: PASS.** O baseline foi executado com o evaluator privado fornecido, sem motivos de invalidação registrados, e o artefato final está preservado em `data/artifacts/research/horizon/comparisons/b2824b02-8b65-4abe-af4e-185648f6eee5/horizon_control.json`.

Este resultado autoriza o início controlado do GR-1 conforme o roadmap. Ele **não** demonstra ganho de capacidade geral, não é evidência de salto e não deve ser comparado como vitória contra uma variante cognitiva.

## Configuração congelada

| Campo | Valor |
|---|---|
| Benchmark | `horizon_control_v1` |
| Missões | 3 missões Forge públicas do piloto (`forge_e2e_01` a `forge_e2e_03`) |
| Modos | `full_plan`, `short_horizon`, `next_action` |
| Modelo solicitado | `ollama` |
| Modelo efetivo | `qwen2.5:0.5b` |
| Seed | `53` |
| Commit registrado | `4ebbe788cdf6f6146142740e7a9366923720c0b5` |
| Traces | 9, sendo uma por missão e modo |
| Evaluator | Privado externo; hash registrado no artefato |
| Injeção de experiência | Desligada (`injection_limit = 0`) |
| Medição | `measurement_valid = true` |
| Motivos de invalidação | Nenhum (`[]`) |

## Verificações metodológicas

| Controle | Resultado |
|---|---:|
| Shared orientation verificada | 9/9 traces |
| Contrato de missão verificado | 9/9 traces |
| Atribuição de modelo verificada | 9/9 traces |
| Atribuição de seed verificada | 9/9 traces |
| Allowlist de ferramentas respeitada | 9/9 traces |
| Teto de budget respeitado | 9/9 traces |
| Tool call antes da primeira decisão | 0/9 traces |
| Erro do evaluator privado | 0/9 traces |
| Avaliação externa registrada quando aplicável | Conforme trace; sem erro de evaluator |
| Writeback verificado indevido | 0 casos observados |

Falhas cognitivas do modelo, como output estruturado inválido, reparos e ausência de conclusão externa, permanecem visíveis no trace e não invalidam a metodologia. Elas também não são convertidas em sucesso atribuído ao modelo.

## Resultados observados

| Modo | Missões | Passes | ATC | SDV | Initial SDV | Repair Recovery Rate | Chamadas LLM médias | Tool calls médias |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `full_plan` | 3 | 0 | 0,000000 | 1,000000 | 0,076923 | 1,000000 | 8,333 | 0,000 |
| `short_horizon` | 3 | 0 | 0,000000 | 0,967391 | 0,967391 | 0,000000 | 32,000 | 0,000 |
| `next_action` | 3 | 0 | 0,000000 | 0,800000 | 0,733333 | 0,250000 | 9,000 | 0,667 |

O `closed_loop_lift` e o `short_horizon_lift` foram ambos `0,000000`. Como esperado de um baseline sem capacidade nova, não há hipótese de ganho a interpretar. A amostra também é deliberadamente pequena para validar apenas a instrumentação inicial; ela não suporta inferência estatística sobre generalização, múltiplas seeds ou famílias unseen.

## Decisão experimental

O GR-0 passa como **baseline metodologicamente válido** porque preservou contrato, modelo, seed, orientação, ferramentas, budget, evaluator privado e fronteira de writeback. O resultado também expõe um ponto de partida importante: com o modelo-base efetivo usado nesta execução, o ATC observado foi zero nos três modos e houve custo relevante de reparo/decisão estruturada em `short_horizon`.

O próximo passo autorizado é implementar somente o **GR-1 — Epistemic State**, atrás de uma flag desligada por padrão, sem hipótese search, previsão, causalidade, contrafactual, MetaReasoner ou backtracking novos. A comparação GR-1 deve preservar o mesmo contrato experimental e manter este artefato imutável como referência.

## Artefato primário

`data/artifacts/research/horizon/comparisons/b2824b02-8b65-4abe-af4e-185648f6eee5/horizon_control.json`

O artefato primário contém traces completos, hashes de orientação e fixture, atribuição de modelo/seed, chamadas LLM, decisões estruturadas, resultados do evaluator, métricas de custo e motivos de validade.

## Referências locais

- `GENERAL_REASONING_ROADMAP.md`
- `HORIZON_V0_7_REPORT.md`
- `ultron/research/horizon_control.py`
- `benchmarks/horizon_control_v1/README.md`
