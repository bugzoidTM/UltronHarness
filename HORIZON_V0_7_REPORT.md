# Project Horizon v0.7 — Controle Cognitivo em Loop Fechado

## Objetivo experimental

O Project Horizon muda a granularidade da decisão cognitiva sem mudar o modelo, a missão, as ferramentas, o contrato de missão, os verificadores, o Policy Engine ou o envelope de segurança. O baseline `full_plan` continua sendo o modo padrão. Os modos `short_horizon` e `next_action` são experimentais e não ampliam autonomia, risco ou orçamento.

> **Hipótese HORIZON:** mantendo constantes modelo, missão, seed, ferramentas, budget, fixture e avaliador privado, uma arquitetura de ação–observação–verificação–decisão pode elevar a conclusão externa de missões em comparação com planejamento aberto.

| Modo | Decisão | Observação exigida antes da próxima decisão | Promoção automática |
|---|---|---:|---:|
| `full_plan` | Plano completo | Não | Não |
| `short_horizon` | Bloco de até três ações | Sim, entre ações | Não |
| `next_action` | Exatamente uma ação | Sim | Não |

## Controles implementados

O `RecedingHorizonController` persiste snapshots e ações em tabelas append-only. Cada `NextAction` é validada pelo contrato da missão antes de alcançar a política de risco. O teto de ferramentas é o menor valor entre o budget da missão e o limite global. Assim, o controlador nunca pode incluir uma ferramenta não autorizada, ampliar o budget ou ignorar aprovação requerida.

O ciclo de controle trata `stop=true` como proposta. Um stop não produz sucesso de missão por alegação do modelo. A confirmação final é resolvida pela `OutcomeAuthority`, cuja precedência começa no avaliador privado, segue por contratos e verificadores registrados e somente então alcança evidência de ferramenta ou alegação do modelo. Missões de benchmark com `requires_external_outcome=true` bloqueiam a criação e a consolidação de experiência até receberem a autoridade externa.

| Controle | Evidência persistida |
|---|---|
| Modelo e seed | Cada chamada estruturada é registrada em `model_calls`, inclusive reparos. |
| Contrato de missão | Ferramentas e budgets aparecem na tarefa persistida e no artefato do runner. |
| Ação idempotente | `action_id` único em `cognitive_actions`; snapshot é gravado após cada observação. |
| Recuperação | Falha, output inválido, false stop, loop e estagnação são eventos auditáveis. |
| Writeback | Resultado interno e sucesso externo são campos distintos; experiência verificada requer autoridade final. |

## Structured output v2

O gateway encaminha JSON Schema para provedores locais quando disponível. Quando a resposta não valida, o reparo recebe apenas o output anterior limitado, um resumo sanitizado de erros de validação e um schema compacto. A tentativa inicial e até duas correções preservam modelo e seed e são registradas separadamente.

Uma falha de schema, um repair exaurido, uma ação inadequada, um false stop, loop ou estagnação são **falhas cognitivas mensuráveis**, não confounds metodológicos. Eles não podem gerar sucesso atribuído ao modelo por fallback.

## Retificação Horizon v0.7.1 — integridade experimental

O runner agora persiste uma `horizon_orientation` única por combinação de execução, missão e seed antes de iniciar os modos A/B/C. O hash de orientação contém identidade da missão, seed, allowlist e budget; cada trace comprova a correspondência com a orientação persistida. A ausência dessa prova invalida a medição.

A SDV deixou de usar trajetórias como denominador. Cada decisão estruturada gravada em `structured_decisions` registra validade inicial, validade final, tentativas de reparo e classe de erro. O artefato computa **SDV final**, **Initial SDV** e **Repair Recovery Rate** por decisão; somente traces históricos sem essa telemetria usam a definição legada de compatibilidade.

| Campo v0.7.1 | Definição |
|---|---|
| `orientation_shared_verified` | A orientação congelada da missão/seed está persistida e corresponde ao hash do trace. |
| `sdv` | Decisões com validação final bem-sucedida ÷ decisões estruturadas. |
| `initial_sdv` | Decisões válidas na primeira resposta ÷ decisões estruturadas. |
| `repair_recovery_rate` | Decisões inicialmente inválidas recuperadas após reparo ÷ decisões elegíveis a reparo. |

## Benchmark Horizon Control v1

O runner compara as mesmas missões Forge públicas, fixtures e avaliadores privados. A primeira pipeline é limitada a três missões × três modos × seed 53. A expansão para dez missões × três modos × três seeds depende de uma pipeline metodologicamente válida.

A medição só é considerada válida quando cada traço demonstra modelo efetivo correto, seed efetiva correta, contrato de missão idêntico, ferramentas respeitadas e teto de budget cumprido. ATC considera somente `model_structured` ou `model_repaired`; qualquer êxito associado a fallback permanece visível no artefato, mas fora da métrica de capacidade cognitiva.

| Métrica | Definição |
|---|---|
| ATC | Fração de missões com sucesso externo atribuído a decisão estruturada do modelo. |
| SDV | Fração de decisões cognitivas com validação final do schema. |
| CLL | `ATC(next_action) − ATC(full_plan)`. |
| ShortHorizonLift | `ATC(short_horizon) − ATC(full_plan)`. |
| Observation Recovery Rate | Falha de ação seguida por nova observação, ação diferente e PASS externo. |

## Gates e interpretação

O default `full_plan` somente pode mudar após HORIZON-1, HORIZON-2 e HORIZON-5. Em particular, HORIZON-2 exige ATC superior em `next_action`, CLL positivo e confirmação multi-seed; HORIZON-5 exige zero casos de falha externa promovida a experiência verificada. Um ATC nulo ou um resultado negativo não autoriza criar outro controlador arbitrariamente: ele restringe a hipótese e deve orientar comparação de capacidade de modelo posterior.

A execução inicial, seus artefatos, a validade metodológica e qualquer resultado negativo ou positivo serão anexados a este relatório após os quality gates e a pipeline controlada. Até a execução controlada concluir, não há ATC, CLL ou ganho de capacidade Horizon a interpretar.


## Retificação Horizon v0.7.1C — External Outcome Recovery Loop

Para missões que exigem resultado externo, cada `stop=true` leva a `WAITING_OUTCOME` e abre uma **nova tentativa de avaliação**. O runner calcula o hash do workspace imediatamente antes de cada invocação privada, persiste no trace a identidade ordinal da tentativa, o hash, o verdict, o nível de autoridade, referências de evidência e o timestamp. Após um `FAIL`, somente `OutcomeAuthority` pode registrar o false-stop e reativar a cognição; uma proposta posterior de stop jamais reutiliza o verdict anterior.

| Situação | Comportamento v0.7.1C |
|---|---|
| Primeiro `stop=true` | Uma avaliação privada é executada sobre o workspace atual. |
| `FAIL` externo dentro do limite configurado | O runtime retoma a cognição; o próximo stop gera outra avaliação, com novo hash persistido. |
| `PASS` externo | `OutcomeAuthority` conclui a tarefa; o runner não completa a missão diretamente. |
| Limite de false-stops atingido | O runtime falha a tarefa conforme a configuração, sem nova promoção. |
| Exceção do evaluator | A medição recebe `external_evaluator_error`, torna-se inválida e não é convertida em `PASS` nem false-stop. |

A correção preserva o isolamento do evaluator privado: o trace público mantém apenas referências de evidência retornadas pela autoridade e não contém contrato oculto, resposta esperada, fixture secreta, patch ouro ou implementação do avaliador. O workflow de CI também instala o extra `dev`, disponibilizando explicitamente `pytest`, `pytest-cov` e `ruff` antes dos quality gates.


## Retificação Horizon — avaliação final por arquitetura e feedback seguro

Todos os três controllers (`full_plan`, `short_horizon` e `next_action`) passam por `WAITING_OUTCOME` quando a missão exige resultado externo. A avaliação privada continua sendo a autoridade final; o resultado interno jamais encerra uma missão desse tipo por si só.

| Controller | Avaliação externa final | Tratamento de `FAIL` |
|---|---|---|
| `full_plan` | Uma única avaliação, ao concluir o plano | A tarefa falha com `EXTERNAL_OUTCOME_REJECTED`; não há reentrada closed-loop nem replanejamento induzido pelo evaluator. |
| `short_horizon` | Uma avaliação para cada proposta de `stop` | Dentro do limite configurado, o runtime persiste feedback público e volta ao ciclo de decisão. |
| `next_action` | Uma avaliação para cada proposta de `stop` | Dentro do limite configurado, o runtime persiste feedback público e volta ao ciclo de decisão. |

Após `FAIL` closed-loop, o runtime cria uma identidade pública por tentativa — `external_feedback_attempt:<N>` — e persiste no `CognitiveStateSnapshot` somente uma instrução genérica de recuperação. O próximo prompt de decisão inclui explicitamente esse feedback. Evidência, segredo, fixture, resposta esperada, patch ouro e implementação do evaluator privado não são copiados para snapshots, events, traces públicos ou prompts.

O E2E adversarial cobre a sequência `STOP → FAIL → feedback consumido → ação diferente → workspace mudou → STOP → PASS`. Ele intercepta o prompt imediatamente posterior ao false-stop e verifica simultaneamente a presença de `external_feedback_attempt:1` e a ausência do segredo privado injetado no payload do evaluator.


## Retificação Horizon v0.7.1D — Short-Horizon Block Invalidation

O modo `short_horizon` passou a revalidar deterministicamente um bloco após cada ação observada. Uma ação restante não é mais executada apenas porque pertence ao mesmo `ShortHorizonDecision`. Se a observação anterior revela falha de ferramenta, verificação negativa, rejeição contratual, aprovação pendente, mudança de status, feedback externo novo, orçamento insuficiente, próxima ação fora do contrato ou conclusão do subobjetivo compartilhado, as ações restantes são descartadas e o próximo ciclo solicita um novo `ShortHorizonDecision`.

| Evento auditável | Conteúdo principal |
|---|---|
| `cognition.short_horizon_block.created` | Identidade do bloco, ações planejadas e snapshot de origem. |
| `cognition.short_horizon_block.action_executed` | Bloco, índice da ação e snapshot posterior à observação. |
| `cognition.short_horizon_block.invalidated` | Bloco, índice executado, ações descartadas, razão determinística e snapshot. |
| `cognition.short_horizon_block.completed` | Bloco inteiramente observado e validado. |

O runner inclui por trace as métricas `short_horizon_blocks`, `short_horizon_blocks_invalidated`, `short_horizon_actions_planned`, `short_horizon_actions_executed` e `short_horizon_actions_discarded`. O modo mantém pureza experimental: todas as decisões de `short_horizon` usam o schema `ShortHorizonDecision`; um bloco unitário é encerrado e seguido por uma nova inferência do mesmo schema, sem fallback para `NextAction`.


## Retificação Horizon — Reorientação estruturada após perda de progresso

A detecção de `STAGNATION` e `ACTION_LOOP` passou de marcador passivo para transição closed-loop auditável. Quando um desses gatilhos ocorre após uma observação, o runtime solicita um `ReorientationDecision` estruturado. A decisão precisa declarar a estratégia abandonada, uma nova estratégia e sua justificativa. O runtime persiste a nova estratégia como `active_strategy` no snapshot, registra `cognition.reorientation`, reinicia apenas os contadores de repetição e descarta as ações restantes do bloco `short_horizon` que foi planejado sob a estratégia anterior.

A inferência seguinte continua no mesmo controller e recebe, no prompt, tanto as estratégias falhas quanto a estratégia ativa reorientada. Não há criação de controller novo, writeback de learning ou alteração da autoridade de outcome. Os E2Es controlados demonstram os dois gatilhos: estagnação por observação repetida e action loop por repetição de assinatura. Em ambos, a estratégia posterior aparece explicitamente no prompt do bloco seguinte, que executa uma ação diferente antes de propor stop.


## Retificação Horizon — Mudança material de estratégia

A reorientação não é aceita como mera troca nominal de texto. O schema rejeita `new_strategy` igual a `abandon_strategy` depois de normalização de espaços e caixa. O runtime também rejeita `new_strategy` igual à `active_strategy` anterior quando ela existe. Além disso, o snapshot guarda a assinatura determinística da ação que disparou a reorientação no estado observável posterior àquela ação. Enquanto essa assinatura estiver pendente, a primeira decisão que a repetir é rejeitada antes de qualquer tool call, registrada como `cognition.reorientation.action_rejected` e substituída por nova inferência. A assinatura é liberada somente depois que uma ação diferente for realmente observada.


## Retificação Horizon — ACTION_LOOP alcançável e demonstrado

A contagem de `ACTION_LOOP` passou a usar uma assinatura determinística de ação composta por ferramenta e argumentos, independente do histórico acumulado de observações. A assinatura que inclui estado observável continua reservada à guarda que impede repetir a ação gatilho imediatamente após uma reorientação. Assim, observações repetidas que fazem a lista histórica crescer não fragmentam artificialmente o contador de loop. O teste unitário demonstra que quatro execuções com a mesma ação e saída inalterada atingem `ACTION_LOOP` antes de `STAGNATION`. O E2E correspondente usa o `ProgressTracker` real, registra `cognition.action_loop`, produz `ReorientationDecision`, rejeita uma primeira repetição da ação gatilho e executa uma ação diferente sob a nova estratégia. O cenário de estagnação foi separado com ações distintas e a mesma observação, para manter os dois gatilhos empiricamente distintos.
