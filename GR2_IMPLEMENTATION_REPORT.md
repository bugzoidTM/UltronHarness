# GR-2 — Prediction Before Observation

## Estado da implementação

O **GR-2 — Prediction Before Observation** foi implementado conforme o roadmap, atrás da feature flag independente `cognition.feature_flags.prediction_before_observation`, cujo valor padrão permanece **`false`**. O GR-0 congelado e o GR-1 continuam reproduzíveis, e nenhum mecanismo GR-3 ou posterior foi iniciado.

A implementação registra uma expectativa antes da execução de uma ação investigativa e somente materializa o outcome depois que a ação produz uma observação e passa pelo fluxo existente de verificação. A previsão não autoriza ferramenta, não substitui a Policy Engine, não altera o budget e não substitui a `OutcomeAuthority`.

> O piloto confirmou a validade da instrumentação; ele **não constitui evidência de ganho cognitivo ou de generalização**.

## Contrato técnico

| Elemento | Implementação |
|---|---|
| Schema | `Prediction` versionado em `ultron/schemas.py` |
| Classificações | `confirm`, `weaken`, `reject`, `uncertain` |
| Estado antes | hipótese, observação esperada, confiança antes, ação, timestamp e IDs da missão/ação |
| Estado depois | observação obtida, status bruto, verificação, confiança depois, classificação, evidência e timestamp |
| Persistência | `cognitive_predictions` e `prediction_observations`, ambas append-only |
| Integração | `full_plan`, `short_horizon` e `next_action` quando ações são executadas |
| Feature flag | `prediction_before_observation: false` por padrão |
| Telemetria | `cognition.prediction.proposed`, `cognition.prediction.observed` e `cognition.prediction.invalid` |
| Benchmark | O artefato registra previsões, pares observados, pendências e métricas por modo |

A previsão é vinculada a uma linha imutável de `cognitive_actions`. A criação é rejeitada se a ação já tiver `executed_at` ou estiver em estado terminal. Uma segunda observação para a mesma previsão também é rejeitada. `waiting_approval` não é tratado como observação: a previsão permanece pendente até a execução efetivamente aprovada.

## Critérios comportamentais e adversariais

O GR-2 foi desenhado para satisfazer a ordem temporal exigida pelo roadmap. O evento `cognition.prediction.proposed` é persistido antes da execução da ferramenta, enquanto `cognition.prediction.observed` só aparece depois da verificação da ação. A previsão e o outcome compartilham `prediction_id` e `action_id`, permitindo auditoria da correspondência.

A camada de schema rejeita outcomes parciais. O serviço rejeita previsão retrospectiva, previsão para ação inexistente, previsão duplicada e observação duplicada. O status `waiting_approval` não pode fechar o ciclo expected/observed. A flag desligada não grava previsões nem eventos novos.

A classificação é conservadora. A ação concluída e verificada produz `confirm`; ação concluída sem verificação produz `weaken`; falha explícita produz `reject`; estados não conclusivos produzem `uncertain`. A confiança posterior é limitada pelo resultado e não pode transformar uma falha em confiança alta.

## Validação automatizada

| Verificação | Resultado |
|---|---:|
| Testes específicos do GR-2 | 5 passed |
| Testes GR-1 + GR-2 | 14 passed |
| Suíte completa | 189 passed, 1 warning |
| Cobertura total | 77,03% |
| Ruff completo | All checks passed |
| Segurança Windows | 12 passed, 1 skipped |
| Smoke E2E | PASS; tarefa concluída, memória persistida e UI local disponível |

A advertência da suíte completa é a depreciação preexistente do `TestClient`/`httpx`; não houve falha de teste associada ao GR-2.

## Piloto privado e ablação mínima

Foi executado um piloto privado pareado com uma missão Forge, os três modos Horizon, seed `53`, o mesmo evaluator privado e o mesmo modelo `local-fallback`. O artefato com a flag desligada e o artefato com a flag ligada foram ambos considerados metodologicamente válidos.

| Variante | Feature flag | `measurement_valid` | Previsões | Observadas | Pendentes | ATC |
|---|---:|---:|---:|---:|---:|---:|
| Baseline pareado | `false` | `true` | 0 | 0 | 0 | 0,000000 |
| GR-2 piloto | `true` | `true` | 1 | 1 | 0 | 0,000000 |

No piloto GR-2, a previsão observada ocorreu no modo `full_plan`; os modos `short_horizon` e `next_action` não produziram ação executada nessa missão específica e, por isso, não fabricaram previsões ou outcomes. O par observado teve `classification=confirm`, `confidence_before=0,5` e `confidence_after=0,85`, com evidência `plan_step:1:2`.

O artefato do piloto GR-2 está em `data/artifacts/research/horizon/comparisons/28ff4f28-3ad5-4c84-98dd-815f0dca906d/horizon_control.json`. O artefato baseline pareado está em `data/artifacts/research/horizon/comparisons/cdb63e48-a228-4602-a5e1-d2ae6132c435/horizon_control.json`.

A métrica `prediction_accuracy` registrada no artefato é uma métrica de **concordância instrumental entre classificação e verificação efetiva**. Ela não deve ser interpretada como prediction accuracy científica final, pois o piloto é pequeno e a expectativa é derivada do contrato/ação atual, não de um conjunto privado de previsões com ground truth independente.

## Integridade metodológica

Os pilotos preservaram o mesmo contrato de missão, orientação compartilhada, seed, allowlist, budget, modelo efetivo e evaluator privado. Ambos registraram `measurement_valid=true` e lista de invalidação vazia. Não foram incluídos fixtures privados, respostas esperadas ou código do evaluator em prompts, snapshots ou relatórios.

A implementação não modifica permissões, aprovação, kill switch, sandbox, credenciais, autoridade externa ou verified writeback. O GR-2 registra expectativa e atualização; não promove memória, experiência ou skill. Um resultado externo negativo continua sendo decidido pela `OutcomeAuthority` e não é convertido em confirmação pela previsão.

## Limitações e decisão de promoção

O **gate de implementação e instrumentação passou**. O **success gate científico do GR-2 ainda não foi declarado positivo**. O piloto tem uma missão, um seed, modelo fallback e nenhum caso suficiente para estimar intervalo de confiança, ganho em tarefas inéditas ou falsificação de premissas em múltiplos domínios. Também não há base para concluir redução de false-stop, aumento de ATC ou ganho de generalização.

Portanto, a decisão correta é manter a flag desligada por padrão e considerar o GR-2 **implementado, validado operacionalmente e não promovido cientificamente**. O próximo passo autorizado é uma coleta pareada maior, com o mesmo modelo-base do GR-0 válido, múltiplas seeds, famílias privadas inéditas, budget pareado, ground truth independente para prediction accuracy e análise pré-registrada de custo e intervalo de confiança.

## Arquivos principais

| Arquivo | Papel |
|---|---|
| `GENERAL_REASONING_ROADMAP.md` | Contrato experimental GR-0 a GR-9 |
| `ultron/cognition/prediction.py` | Serviço append-only do GR-2 |
| `ultron/schemas.py` | Schemas `Prediction`, `PredictionObservation` e classificações |
| `ultron/db.py` | Tabelas `cognitive_predictions` e `prediction_observations` |
| `ultron/core/receding_controller.py` | Integração expected/observed nos modos Horizon |
| `ultron/core/orchestrator.py` | Integração de previsões em `full_plan` e continuations |
| `ultron/research/horizon_control.py` | Feature variant e coleta de métricas do benchmark |
| `tests/test_prediction_before_observation.py` | Testes GR-2 unitários, comportamentais e adversariais |
| `data/artifacts/research/horizon/comparisons/28ff4f28-3ad5-4c84-98dd-815f0dca906d/horizon_control.json` | Piloto GR-2 ligado |
| `data/artifacts/research/horizon/comparisons/cdb63e48-a228-4602-a5e1-d2ae6132c435/horizon_control.json` | Baseline pareado desligado |
