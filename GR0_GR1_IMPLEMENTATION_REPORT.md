# HORIZON v0.8 — Relatório GR-0 e GR-1

## Estado da entrega

O **GR-0 frozen baseline** foi concluído e considerado metodologicamente válido. Após esse gate, o **GR-1 — Epistemic State** foi implementado de forma incremental, com feature flag desligada por padrão, persistência auditável e testes comportamentais/adversariais. Nenhum mecanismo GR-2 ou posterior foi implementado.

O resultado não demonstra salto de capacidade geral. O GR-0 serve como referência congelada; o GR-1 está pronto para futura ablação de desempenho, mas ainda não deve ser promovido com base apenas nos testes locais.

## GR-0 — Baseline congelado

| Controle | Valor |
|---|---|
| Benchmark | `horizon_control_v1` |
| Missões | `forge_e2e_01`, `forge_e2e_02`, `forge_e2e_03` |
| Modos | `full_plan`, `short_horizon`, `next_action` |
| Modelo efetivo | `qwen2.5:0.5b` via alias `ollama` |
| Seed | `53` |
| Traces | 9 |
| Injeção de experiência | Desligada |
| `measurement_valid` | `true` |
| Motivos de invalidação | Nenhum |
| Evaluator | Privado externo, hash registrado |
| Orientação compartilhada | Verificada em 9/9 traces |
| Contrato e budget | Verificados em 9/9 traces |
| Tool call antes da primeira decisão | 0/9 traces |

Artefato primário: `data/artifacts/research/horizon/comparisons/b2824b02-8b65-4abe-af4e-185648f6eee5/horizon_control.json`.

### Métricas observadas

| Modo | ATC | SDV | Initial SDV | Repair Recovery Rate | LLM calls médias | Tool calls médias |
|---|---:|---:|---:|---:|---:|---:|
| `full_plan` | 0,000000 | 1,000000 | 0,076923 | 1,000000 | 8,333 | 0,000 |
| `short_horizon` | 0,000000 | 0,967391 | 0,967391 | 0,000000 | 32,000 | 0,000 |
| `next_action` | 0,000000 | 0,800000 | 0,733333 | 0,250000 | 9,000 | 0,667 |

O `closed_loop_lift` e o `short_horizon_lift` foram `0,000000`. Isso é um resultado de baseline, não uma falha de validade. O evaluator privado rejeitou as conclusões observadas nos três modos, e essa rejeição foi mantida como outcome autoritativo, sem writeback verificado indevido.

## GR-1 — Implementação

A implementação foi limitada ao estado epistêmico explícito e não criou um controller novo. O módulo `ultron/cognition/epistemic.py` fornece estado inicial, observação, registro explícito de inferência, premissa, hipótese e desconhecido, além de resumo estruturado para prompts. O schema `EpistemicState` separa os tipos `FACT`, `INFERENCE`, `ASSUMPTION`, `HYPOTHESIS` e `UNKNOWN`, mantém confidence e evidência e rejeita tanto mistura de tipos quanto promoção silenciosa de hipótese a fato.

A coluna `cognitive_snapshots.epistemic_state_json` mantém os estados append-only. A flag `cognition.feature_flags.epistemic_state` foi adicionada ao `config/default.yaml` com valor `false`. Quando ativa, o controller registra o estado inicial, incorpora observações de orientação e de ferramenta, emite `cognition.epistemic_state.updated` e inclui apenas um resumo estruturado no prompt do `full_plan`, `short_horizon` e `next_action`. Quando desligada, o snapshot permanece compatível e a coluna fica nula.

O update de observação é deliberadamente conservador: saídas observadas entram como fatos com proveniência; falhas entram como fatos sobre a falha e geram unknowns sobre a condição de sucesso; verificações negativas geram unknowns adicionais. O módulo não gera hipóteses concorrentes, previsões, relações causais, contrafactuais, seleção meta-racional ou backtracking novo. Esses itens continuam reservados aos próximos experimentos do roadmap.

## Evidência de testes

| Verificação | Resultado |
|---|---|
| Testes específicos GR-1 | 9 passed |
| Suíte `tests` | 184 passed, 1 warning |
| Cobertura total | 77,03% |
| Testes de segurança Windows | 12 passed, 1 skipped |
| Testes de agentes | 9 passed, 1 xfailed |
| Ruff completo | All checks passed |
| Smoke E2E determinístico | PASS; tarefa concluída, 36 eventos, memória persistida e UI HTTP 200 |
| Saúde da API/UI | Banco saudável e UI HTTP 200 |

O smoke padrão com o modelo `qwen2.5:0.5b` ultrapassou a janela de polling e, em uma tentativa posterior, o modelo produziu um caminho fora do workspace permitido. Isso foi corretamente rejeitado pela fronteira de segurança. O smoke completo passou com `ULTRON_MODEL_PRIMARY=local-fallback`, sem relaxar permissões; a integração do GR-1 com flag ligada passou na suíte específica em ambiente isolado.

## Invariantes preservados

O shared orientation, a telemetria estruturada, a `OutcomeAuthority`, a recuperação de false-stop, a invalidação de short-horizon, a reorientação estruturada, o verified writeback, as permissões e o evaluator privado não foram substituídos nem contornados. O GR-1 somente acrescenta uma camada de representação e proveniência; a execução continua passando pelo mesmo contrato de missão, Policy Engine, verificação, sandbox e autoridade final.

## Próximo passo autorizado

O próximo experimento é a **ablação GR-1** com a mesma missão, seed, modelo, budget, ferramentas, orientação e evaluator do baseline. Deve comparar flag desligada versus ligada e medir classificação epistêmica, false-stop recovery, ATC, SDV, chamadas, tokens e latência. Não se deve avançar para GR-2 antes de registrar essa ablação e verificar ausência de regressão de segurança e de writeback.

## Arquivos principais

| Arquivo | Papel |
|---|---|
| `GENERAL_REASONING_ROADMAP.md` | Roadmap aprovado GR-0 a GR-9 |
| `GR0_BASELINE_REPORT.md` | Relatório específico do baseline congelado |
| `GR0_GR1_IMPLEMENTATION_REPORT.md` | Este relatório consolidado |
| `ultron/cognition/epistemic.py` | Núcleo do estado epistêmico GR-1 |
| `tests/test_epistemic_state.py` | Testes comportamentais e adversariais GR-1 |
| `data/artifacts/research/horizon/comparisons/b2824b02-8b65-4abe-af4e-185648f6eee5/horizon_control.json` | Artefato primário GR-0 |
