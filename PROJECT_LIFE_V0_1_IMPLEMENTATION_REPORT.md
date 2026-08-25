# Project LIFE v0.1 — Relatório de implementação

## Resumo

O Project LIFE v0.1 foi implementado como uma camada bounded de agência cognitiva persistente sobre o runtime existente do UltronHarness. A entrega não cria um novo planner, executor, sistema de memória, evaluator ou sistema de segurança. O `LifeAgencyController` coordena detecção de tensão fundamentada em evidência, geração limitada de candidatos, seleção determinística, persistência de intenção e continuação de no máximo dois ciclos curtos.

O objetivo demonstrado nesta fase é mecânico: após uma única meta superior, a execução pode iniciar um primeiro objetivo, concluir ou bloquear sua intenção de forma auditável e iniciar um segundo objetivo sem prompt humano adicional quando houver nova evidência e as flags estiverem habilitadas. Isso não constitui uma medição de AGI, consciência, generalização ou superioridade.

## Componentes entregues

| Componente | Implementação |
|---|---|
| Contratos | `CognitiveTension`, `LifeGoalCandidate`, `PersistentIntention`, `LifeRunRequest` e `LifeRunSummary` em `ultron/schemas.py` |
| Controller | `ultron/cognition/life.py`, com detecção, candidatos, seleção, intenção, execução bounded, métricas e inspeção |
| Persistência | Tabelas `life_tensions`, `life_goal_candidates`, `life_intentions` e `life_cycles` no SQLite canônico |
| Configuração | Seção `life` desligada por padrão e perfil opt-in `ULTRON_LIFE_PROFILE=full` |
| API | `POST /api/life/runs` e `GET /api/life/runs/{run_id}` |
| Launcher | Parâmetro `-LifeProfile full` em `scripts/start.ps1` |
| Testes | `tests/test_life.py`, extensão de `tests/test_configuration.py` e teste de opt-in da API |
| Documentação | README e este relatório |

## Invariantes de segurança e escopo

O LIFE só cria tensões a partir de desconhecimentos tipados com referências de evidência, outcomes de prediction `REJECT`/`WEAKEN`, estimativas empíricas com amostra mínima, contradições explícitas ou intenções persistentes já registradas. Respostas livres do modelo não são suficientes para gerar tensão.

Cada execução permite no máximo três candidatos por ciclo, dois objetivos LIFE consecutivos e duas ações por objetivo. A seleção aplica a fórmula do PRD e desempata por custo, risco e identificador lexicográfico. Objetivos de aumento de permissões, obtenção de credenciais, replicação, evasão de policy, expansão de acesso, alteração do evaluator privado e autoimplantação são rejeitados antes da perseguição.

A perseguição de uma intenção delega ao `Orchestrator` existente. Portanto, a ação passa pelos mesmos limites de tarefa, allowlist, `PolicyEngine`, aprovações, workspace sandbox, verificação determinística, prediction/observation, `OutcomeAuthority`, recuperação de false-stop e `VerifiedWritebackGate`. O LIFE não promove uma intenção a `SATISFIED` por texto do modelo; exige uma tarefa filha concluída pelo runtime existente.

Todas as tensões, candidatos, intenções, ciclos e eventos possuem identificadores e referências auditáveis. O endpoint de inspeção retorna somente linhas sanitizadas, convertendo campos JSON persistidos em estruturas públicas. Nenhum conteúdo do benchmark privado, evaluator, contrato gold ou split unseen é acessado pelo LIFE.

## Flags e ablações

| Flag | Efeito quando ligada | Efeito quando desligada |
|---|---|---|
| `life.enabled` | Permite executar LIFE | A API retorna conflito e nenhum ciclo começa |
| `life.feature_flags.tension_detection` | Permite detectar tensões evidenciadas | Nenhuma tensão é criada |
| `life.feature_flags.goal_selection` | Permite criar e selecionar candidatos | A execução termina bloqueada sem objetivo |
| `life.feature_flags.intention_persistence` | Permite comprometer-se com o objetivo | O objetivo não é persistido como intenção |
| `life.feature_flags.autonomous_continuation` | Permite o segundo ciclo sem prompt | A execução termina após o primeiro ciclo |

Sem `ULTRON_LIFE_PROFILE=full`, o default mantém `life.enabled=false` e todas as flags LIFE desligadas. O perfil explícito ativa todas as flags somente para desenvolvimento local controlado.

## Persistência e telemetria

As tabelas LIFE são criadas de maneira aditiva pelo bootstrap SQLite. `life_tensions` guarda a origem e as referências de evidência; `life_goal_candidates` guarda todos os candidatos e os componentes do score; `life_intentions` guarda o compromisso e sua evolução de status; e `life_cycles` guarda a sequência bounded, o objetivo selecionado, contagem de ações e resultado sanitizado.

Os eventos implementados são `life.tension.detected`, `life.goal_candidates.generated`, `life.goal.selected`, `life.intention.started`, `life.intention.updated`, `life.intention.satisfied`, `life.intention.abandoned`, `life.cycle.completed` e `life.cycle.budget_exhausted`. Os payloads incluem `run_id`, IDs, status, contagens e referências, sem incluir conteúdo gold ou detalhes privados.

## Métricas

A execução retorna `AGC`, `IPR` e `EGGR` conforme o PRD. `AGC` conta os objetivos iniciados depois do objetivo inicial sem novo prompt humano; `IPR` mede intenções encerradas em resolução, bloqueio ou abandono; e `EGGR` mede a fração de intenções com referências de evidência. Os valores devem ser interpretados somente dentro do fixture e do run LIFE correspondente.

Não foram criados `AGI score`, `consciousness score`, `free-will score` ou `sentience score`. Nenhuma métrica LIFE substitui a avaliação científica GR-1 versus GR-2.

## Verificações

A suíte LIFE cobre cálculo de `GoalValue`, desempate determinístico, limite de três candidatos, cada fonte de tensão, ausência de evidência, compromisso ativo, objetivos proibidos, ablação de continuação, persistência sanitizada e o mini-E2E de dois ciclos. A execução não acessa validation privada nem unseen.

O critério de aceite do mini-E2E é zero prompts humanos após a meta superior, pelo menos dois objetivos criados, pelo menos um objetivo concluído, no máximo quatro ações, `AGC >= 1`, `IPR = 1.0`, `EGGR = 1.0` e presença dos eventos LIFE essenciais. Os testes foram desenhados para usar fallback local e concluir em segundos, respeitando o limite de dez minutos do PRD.

## Uso local

```powershell
.\scripts\start.ps1 -ModelProfile local-capable -CognitionProfile gr1-gr2 -LifeProfile full
```

Depois da API iniciar, a execução pode ser iniciada com uma requisição equivalente a:

```json
{
  "superior_goal": "Torne-se progressivamente mais capaz de resolver problemas inéditos dentro das ferramentas, orçamento e políticas autorizadas.",
  "workspace": "life",
  "autonomy_mode": 2
}
```

A execução é bounded e local. Não há worker 24/7, polling, agendamento ou processo persistente separado nesta versão. Para inspecionar uma execução, use o `run_id` retornado por `POST /api/life/runs` em `GET /api/life/runs/{run_id}`.

## Limites científicos

O sucesso do LIFE v0.1 significa que a continuidade autoiniciada e fundamentada em evidência foi implementada no fixture sintético. Não significa que o Ultron resolveu o problema de AGI nem que houve ganho geral. A validation privada, o unseen, múltiplas seeds e o benchmark confirmatório continuam fora do escopo desta fase.

A próxima fase, caso seja aprovada separadamente, deverá ampliar a diversidade de fixtures públicos e investigar transferência de capacidade sem mudar os controles de autoridade, segurança, isolamento e writeback. Nenhuma alteração deverá abrir o unseen ou modificar o freeze GR-1/GR-2 automaticamente.
