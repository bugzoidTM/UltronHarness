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
