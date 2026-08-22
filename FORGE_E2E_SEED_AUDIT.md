# Auditoria de seed — Forge E2E

A análise confirmou que a seed do benchmark era anteriormente apenas um campo de relatório. Ela não era transmitida ao `ModelGateway.generate()` durante planejamento ou replanejamento.

A correção adiciona `planning_seed` ao orquestrador, propaga a seed para todas as chamadas de `_make_plan()` — inclusive revisões após falha — e persiste a coluna `seed` em `model_calls`. A migração é compatível com bancos SQLite existentes.

| Campo | Validação da execução corrigida |
|---|---:|
| Seed solicitada pelo benchmark | `49` |
| Seed efetiva registrada em `model_calls` | `49` |
| `seed_attribution_verified` | `true` |
| Modelo efetivo | `qwen2.5:3b` |
| `model_attribution_verified` | `true` |
| Origem do plano | `fallback_after_model_error` |
| Validade da métrica E2E | `false`, por ausência de JSON estruturado do modelo |

> Uma execução multi-seed só poderá ser consolidada quando cada missão tiver `model_attribution_verified = true`, `seed_attribution_verified = true` e `planner_source = model_structured`. Caso contrário, o resultado deve permanecer inelegível, sem inferência sobre ATC ou ganho de capacidade.
