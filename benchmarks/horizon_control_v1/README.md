# Horizon Control v1

Este benchmark compara arquiteturas de controle sobre as mesmas dez missões públicas de `benchmarks/forge_e2e_v1/tasks.yaml`.

| Controle congelado | Regra |
|---|---|
| Missão, fixture e contrato | Reutilizados integralmente do Forge E2E v1. |
| Modelo e seed | Idênticos em `full_plan`, `short_horizon` e `next_action`. |
| Ferramentas e orçamento | Vinculados ao contrato persistido da tarefa; o teto efetivo é o mínimo entre missão e runtime global. |
| Policy, verifiers e sandbox | Reutilizados sem relaxamento. |
| Avaliação | O evaluator privado externo é a fonte de ATC e precede qualquer writeback. |
| Experiência | Router fresh-only; injeção desligada. |

Os contratos e avaliadores privados permanecem fora deste repositório. O runner registra hashes de fixture, contrato e evaluator, além de atribuição de modelo, seed, modo de controle e origem da decisão.

Uma falha cognitiva — JSON inválido após reparo, ação inadequada, false stop, loop ou estagnação — é registrada como resultado válido. Uma corrida só é metodologicamente inválida por confound de modelo, seed, contrato, fixture, evaluator, modo, segurança ou teto de ações.
