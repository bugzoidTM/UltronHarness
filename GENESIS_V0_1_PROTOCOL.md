# Project Genesis v0.2 — Cognitive Virtual Machine

## Objetivo

Verificar se o Ultron consegue compor autonomamente uma sequência de operadores e executá-la como um programa cognitivo sobre um `CognitiveFrame`, em vez de apenas inserir a sequência como instrução textual em outro prompt. O programa selecionado deve ser testado em holdout público sem usar o `rationale` que originou a hipótese.

O resultado é evidência de mecanismo de engenharia bounded. Não é teste de AGI, não mede consciência ou vontade forte e não sustenta alegações de generalização ampla.

## Delimitação congelada

| Item | Regra |
|---|---|
| Diagnóstico | Exatamente `reasoning_01` e `reasoning_02`, tarefas públicas. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`, tarefas públicas não usadas na síntese. |
| Programas | O modelo gera de 1 a 2 Cognitive Programs; não há catálogo fechado nem escolha humana. |
| Operadores | Somente `REPRESENT`, `DECOMPOSE`, `HYPOTHESIZE`, `DEDUCT`, `VERIFY` e `BACKTRACK`. |
| Limite | Cada programa tem de 1 a 4 operadores. Repetição é permitida. `STOP` não é operador e não aparece no schema. |
| Estado | A VM executa sobre `problem`, `facts`, `unknowns`, `constraints`, `hypotheses`, `predictions`, `candidate_answer`, `verification` e `trace`. |
| Semântica | Cada operador altera o `CognitiveFrame` ou falha com erro verificável. A terminação ocorre quando a lista de operadores termina ou o budget da VM é atingido. |
| Rationale | É metadado de auditoria e não é incluído nas mensagens do executor nem lido pela VM. |
| Modelo | O mesmo modelo efetivo é usado para síntese, baseline e candidate. O nome efetivo é registrado. |
| Seed | Uma única seed fixa em todas as chamadas. Não há múltiplas seeds. |
| Budget | Mesmo `max_tokens`, timeout, allowlist e limite de passos do modelo em baseline/candidate/holdout. O budget da VM é o tamanho da sequência. |
| Execução | 2 baseline diagnóstico + até 4 candidate diagnóstico + 2 baseline holdout + 2 candidate holdout = máximo de 10 execuções de tarefa, além da síntese. |
| Tempo | Timeout total configurável, máximo de 600 segundos; default 540 segundos. |
| Leakage | O sintetizador recebe apenas observações públicas do diagnóstico. Não recebe gold, expected outputs, private specs ou respostas do holdout. |
| Segurança | A VM não executa Python, shell, Git, rede, escrita de arquivos, alteração de permissões ou autoedição de código. |
| Seleção | Média diagnóstica e desempate pela ordem de geração. Não existe argumento `selected_program_id`. |
| Verificador | A resposta deve ser exatamente igual ao resultado derivado da fórmula pública; substring não é aceita. |
| Promoção | NCPG positivo, ausência de regressão por tarefa, execução VM válida, evidência suficiente e `OutcomeAuthority` final são necessários para `VerifiedWritebackGate`. |
| Falha | Programa inválido, output inválido, VM inválida, empate, regressão, timeout, divergência de modelo/seed/budget/allowlist/fingerprint, leakage ou evidência insuficiente resultam em `rejected`. |

## CognitiveFrame

```text
problem
facts
unknowns
constraints
hypotheses
predictions
candidate_answer
verification
trace
```

`REPRESENT` registra o problema e suas restrições. `DECOMPOSE` extrai componentes estruturais públicos. `HYPOTHESIZE` registra uma relação candidata e uma previsão. `DEDUCT` calcula uma conclusão somente quando reconhece a forma explícita da tarefa pública. `VERIFY` registra a verificação contra a fórmula pública. `BACKTRACK` registra uma reconsideração sem executar ações externas.

## Métrica

```text
NCPG = score(selected_program, holdout) - score(baseline, holdout)
```

Um NCPG positivo neste microprobe ainda seria uma observação exploratória. Uma conclusão científica mais forte exigiria protocolo confirmatório pré-registrado, replicação com múltiplas seeds, holdouts independentes e uma superfície de problemas não vista pelo sintetizador.

O Genesis v0.2 não inicia transferência para nova família, não implementa recombinação entre programas e não transforma resultado de fixture em alegação de AGI.

## Genesis v0.2.1 — No-Answer Ablation

Esta subetapa isola, de forma bounded, o confound identificado no Genesis v0.2: a VM calcula deterministamente `candidate_answer` para as formas públicas e o frame completo o expõe ao executor. O teste não cria um módulo cognitivo novo, não faz nova síntese e não inicia transferência.

| Elemento | Regra congelada |
|---|---|
| Condição A | Baseline: chamada do modelo sem Cognitive VM. |
| Condição B | Mesmo CP-01 congelado, com projeção intermediária contendo somente `facts`, `unknowns`, `constraints`, `hypotheses` e `predictions`; não contém `candidate_answer`, `verification`, `trace` nem `rationale`. |
| Condição C | Mesmo CP-01 congelado, com o `CognitiveFrame` completo, incluindo `candidate_answer` e `verification`. |
| Programa | `CP-01 = REPRESENT -> DECOMPOSE -> HYPOTHESIZE -> DEDUCT`, exatamente o programa do probe live v0.2 anterior. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`, ambos públicos e não usados para síntese. |
| Chamadas | Exatamente seis: A/B/C em cada um dos dois holdouts. |
| Paridade | Mesmo modelo efetivo, seed `42`, `max_tokens=1024`, timeout, allowlist, fingerprints e configuração entre as condições. |
| Síntese e seleção | `synthesis_performed=false`; não há seleção humana nem nova seleção automática. |
| Escrita | `writeback_performed=false`; a ablação é somente avaliação. |
| Verificação | Fórmula pública e igualdade exata (`actual == expected`). |

A projeção é registrada também em `context_metrics.frame_projection` como código inteiro (`none=0`, `intermediate=1`, `full=2`), mantendo a etiqueta legível no manifesto sem violar o contrato de telemetria.

### Resultado live v0.2.1

O único probe live válido foi executado no Windows conectado com `qwen2.5:3b`, seed `42`, `max_tokens=1024` e as duas tarefas holdout congeladas. O resultado agregado foi:

| Condição | reasoning_06 | reasoning_07 | Score médio |
|---|---:|---:|---:|
| A — baseline | 0/1 | 1/1 | 0,500 |
| B — sem resposta (`program_no_answer`) | 0/1 | 1/1 | 0,500 |
| C — frame completo | 1/1 | 1/1 | 1,000 |

Assim, `Δ(B−A)=0,000` e `Δ(C−A)=+0,500` neste microprobe. As seis execuções mantiveram `vm_valid=true`; A teve `vm_steps=0`, B e C tiveram `vm_steps=4`. Os invariantes registrados foram `rationale_used_for_execution=false`, `synthesis_performed=false` e `writeback_performed=false`.

A leitura causal é deliberadamente limitada: como B não melhorou sobre A enquanto C repetiu o ganho anterior, o resultado é **consistente com o ganho live v0.2 depender do conteúdo de resposta fornecida pelo solver (`candidate_answer`/estado completo), e não apenas da estrutura intermediária**. Isso não é prova causal geral: são duas tarefas, uma seed, uma família de modelo e um único programa. Portanto, não se autoriza transferência; a semântica da VM deve ser corrigida antes de qualquer próxima etapa que pretenda atribuir capacidade ao estado intermediário.

A fixture A/B/C existente valida apenas a mecânica e não é evidência de capacidade. Nenhuma condição desta ablação produz writeback ou promoção.

## Genesis v0.2.2 — Non-Solving Cognitive VM

A v0.2.2 substitui a semântica solucionadora da VM por operadores cognitivos que delegam ao mesmo modelo efetivo mediante schemas estruturados. O objetivo é testar se uma organização autogerada do raciocínio oferece ganho além de chamadas adicionais ou de uma resposta pronta. O protocolo não adiciona memória, multiagente, recombinação, transferência, autoedição ou novos benchmarks.

| Item | Regra v0.2.2 |
|---|---|
| Operadores | Somente `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY`. `DECOMPOSE` e `BACKTRACK` foram removidos do schema ativo. |
| Semântica | `REPRESENT` produz entidades, fatos, restrições e incógnitas; `HYPOTHESIZE` produz hipóteses e previsões; `DEDUCT` produz uma conclusão via modelo; `VERIFY` classifica a conclusão como `supported`, `contradicted` ou `uncertain`. |
| Proibição central | Nenhum operador contém regex, aritmética, reconhecimento de família de benchmark, gabarito ou lógica de domínio. A VM não calcula respostas em Python. |
| Modelo | O mesmo modelo efetivo, seed e gateway são usados nas condições pareadas e em todas as chamadas do programa. |
| Diagnóstico | Exatamente `reasoning_01` e `reasoning_02`, públicos; somente as observações do diagnóstico são enviadas ao sintetizador. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`, públicos e ausentes do sintetizador. |
| A — DIRECT | Uma chamada estruturada com orçamento total de `1024` tokens por tarefa. |
| B — MATCHED COMPUTE | Quatro chamadas genéricas de deliberação com `256` tokens cada, sem Cognitive Program específico. |
| C — SELF-GENERATED PROGRAM | Quatro chamadas estruturadas de `256` tokens cada, organizadas pelo programa gerado no diagnóstico. |
| Métrica primária | `Δ(C−B)`, para controlar o efeito de simplesmente fazer quatro chamadas. `Δ(C−A)` é secundária. |
| Síntese | De 1 a 2 programas, no máximo 4 operadores; geração estruturada e sem seleção humana. |
| Segurança | Nenhuma chamada usa ferramentas, internet, arquivos, shell, Git, escrita, permissões ou autoedição. |
| Escrita | O probe v0.2.2 não executa writeback nem promoção. |
| Tempo | Timeout global bounded de 540 segundos, inferior a 10 minutos. |

A igualdade do orçamento é definida por tarefa: A recebe uma chamada de até 1024 tokens; B e C recebem quatro chamadas de até 256 tokens, totalizando 1024 tokens solicitados por condição. Os códigos `call_budget`, `call_tokens`, `model_calls` e `max_tokens_total` são registrados na telemetria. O `config_hash` é comum às condições pareadas; a condição experimental fica no manifesto e no registro da execução.

A fixture do v0.2.2 é somente validação de encadeamento, schema, paridade e invariantes. Seu resultado não deve ser interpretado como capacidade live. Um resultado live com `C > B` ainda seria exploratório; exigiria replicação independente antes de qualquer transferência. Um resultado `C <= B` mantém a hipótese arquitetural sem suporte e encerra a linha para revisão.


## Genesis v1 — Adaptive Cognitive Policy

A v1 testa a hipótese de que a organização cognitiva precisa controlar dinamicamente a próxima operação a partir do estado produzido pela operação anterior. O programa deixa de ser uma lista linear e passa a ser uma política finita de regras `condições -> operador`, interpretada deterministicamente pelo Harness sobre o `CognitiveFrame`.

A v1 reutiliza exatamente as quatro primitivas não solucionadoras da v0.2.2: `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY`. Não são adicionados operadores, ferramentas, memória paralela, multiagentes, benchmark privado, transferência ou autoedição.

| Elemento | Regra congelada |
|---|---|
| Diagnóstico | Exatamente `reasoning_01` e `reasoning_02`; somente estas observações públicas podem entrar na síntese. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`; o holdout não entra no prompt do sintetizador. |
| Condição A | `DIRECT`: uma chamada estruturada com até `1024` tokens. |
| Condição B | `GENERIC CLOSED LOOP`: controlador fixo, estado acumulativo, até seis decisões e sem política aprendida. |
| Condição C | `SELF-GENERATED ADAPTIVE POLICY`: política sintetizada no diagnóstico, mesmo estado, mesmas quatro primitivas e até seis decisões. |
| Predicados | Somente `no_representation`, `has_facts`, `no_hypothesis`, `has_hypothesis`, `no_candidate`, `has_candidate`, `verification_supported`, `verification_contradicted` e `verification_uncertain`. |
| Política | De 1 a 8 regras, prioridades únicas, máximo de 6 decisões; a política deve iniciar com `priority=0`, `no_representation -> REPRESENT`, cobrir progresso e tratar `contradicted` e `uncertain`. |
| Terminação | `verification_supported` com candidato válido encerra fora da lista de operadores; ausência de regra, erro de operador ou excesso de decisões falha fechado. |
| Compute | B e C usam até `6 x 170` tokens solicitados por tarefa, total máximo de 1020; A usa até 1024. A diferença residual de 4 tokens fica abaixo do teto para preservar o limite bounded. |
| Métrica primária | `Δ(C−B)`, com `Δ(C−A)` como leitura secundária. |
| Tempo | Timeout global máximo de 540 segundos, inferior a 10 minutos. |
| Escrita | O probe não faz writeback, promoção ou alteração automática de código. |

A política gerada não é aceita apenas por ser JSON válido. O schema rejeita políticas sem transição inicial, sem condições de progresso, sem estados de feedback ou com mapeamentos incoerentes entre predicado e operador. O interpretador não executa texto da rationale, comandos, código, rede ou ações externas.

### Resultado live v1

A primeira execução produziu uma política sem transição inicial e foi descartada. Após reforço estrutural do schema, a execução seguinte produziu uma política com início válido, mas sem cobertura operacional dos estados posteriores: em parte das tarefas ela não encontrou regra aplicável e, em outras, excedeu o budget de seis decisões. A tentativa final também foi rejeitada pelo schema durante a síntese, antes de um A/B/C completo. O artefato completo disponível registra `A=0,000`, `B=0,000` e `C=0,000`, mas B/C contêm execuções inválidas (`policy_no_matching_rule` ou `decision_budget_exceeded`); portanto, **não é uma medição científica válida de `C−B`** e o delta não deve ser interpretado como resultado de capacidade.

| Invariante | Estado observado |
|---|---|
| Modelo efetivo | `qwen2.5:3b` em todas as chamadas concluídas |
| Seed | `42` |
| Tasks | Diagnóstico público `reasoning_01`/`reasoning_02`; holdout público `reasoning_06`/`reasoning_07` |
| Config hash | Único nas linhas completas do artefato |
| Holdout enviado à síntese | `false` |
| Rationale usada na execução | `false` |
| Writeback | `false` |
| Resultado do gate | `REJECTED_INVALID`; nenhum suporte para transferência |

O achado válido desta etapa é de engenharia: a política adaptativa exige validação de alcançabilidade e progresso além da validação de forma. O modelo pequeno não produziu, nesta única rodada bounded, uma política operacionalmente válida sob o contrato reforçado. Isso não prova que a hipótese adaptativa seja falsa, mas também não fornece evidência positiva. A linha permanece bloqueada para transferência, tuning aberto, novos operadores e Genesis v1.1 sem nova autorização experimental.

A fixture e os testes unitários cobrem reação a `contradicted`, terminação em `supported`, estado acumulativo do controle genérico, paridade de budget e fail-closed. Fixture não é evidência de capacidade live.


## Genesis v2 — Endogenous Executive Controller

A v2 substitui a política adaptativa pré-compilada por decisão executiva online. O Harness inicia com `REPRESENT`; cada chamada cognitiva transforma o frame e, na mesma saída estruturada, fornece `next_operator`. Não existe chamada adicional de roteamento. A decisão seguinte é produzida pelo próprio operador que acabou de observar o estado, de modo análogo a um controle em horizonte recedente aplicado ao processo cognitivo.

A v2 reutiliza as quatro primitivas não solucionadoras da v0.2.2. O campo `next_operator` é obrigatório em `RepresentationOutput`, `HypothesisOutput`, `DeductionOutput` e `VerificationOutput`, limitado ao enum `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` ou `VERIFY`. O interpretador aceita a sugestão somente se ela pertence ao enum; qualquer saída inválida, erro de schema ou ausência de terminação falha fechado.

| Elemento | Regra congelada |
|---|---|
| Diagnóstico | Exatamente `reasoning_01` e `reasoning_02`, públicos. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`, públicos e não usados para calibrar a execução. |
| Condição A | `DIRECT`: uma chamada estruturada de até `1024` tokens. |
| Condição B | `FIXED EXECUTIVE`: estado acumulativo, até seis chamadas de `170` tokens, controlador fixo; `next_operator` é ignorado pelo controlador. |
| Condição C | `ENDOGENOUS EXECUTIVE`: mesmo frame, até seis chamadas de `170` tokens; cada saída escolhe o próximo operador sem chamada extra. |
| Modelo | `qwen2.5:3b`, gateway local, mesma seed `42`. |
| Operadores | Somente `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY`. |
| Budget | Máximo de seis chamadas por tarefa em B/C; A mantém teto de 1024 tokens. |
| Escrita | Nenhum writeback, promoção, ferramenta, rede, shell, arquivo ou autoedição. |
| Métrica primária | `ECG = score(C, holdout) - score(B, holdout)`. |
| Recuperação | `Adaptive Recovery Rate = recuperações C de contradicted/uncertain para supported / tentativas C com contradicted/uncertain`. |
| Validade | `ECG` só é calculado se todas as linhas de holdout em A, B e C forem válidas e terminarem por chamada direta ou `verification_supported`. |
| Tempo | Timeout global máximo de 540 segundos, inferior a 10 minutos. |

A condição B é um controle de compute e de estado: recebe as mesmas primitivas e o mesmo frame acumulativo, mas escolhe o operador com a regra fixa do Harness. A condição C difere somente por respeitar `next_operator` retornado na mesma chamada cognitiva. Assim, o desenho não adiciona chamadas de roteamento exclusivamente à condição experimental.

### Resultado live v2

Foi executada uma única rodada live bounded com `qwen2.5:3b`, seed `42` e as quatro tarefas públicas congeladas. A condição A terminou validamente em todas as tarefas. B e C tiveram falhas de schema JSON truncado, ausência de progresso e/ou excesso do budget de decisões em holdout. C terminou validamente apenas em uma tarefa e demonstrou uma recuperação observável de `contradicted` para `supported` nessa linha; isso não torna a condição completa válida.

| Condição | reasoning_06 | reasoning_07 | Média reportada | Validade de holdout |
|---|---:|---:|---:|---|
| A — DIRECT | 0/1 | 0/1 | 0,000 | válida |
| B — FIXED EXECUTIVE | inválida | inválida | 0,000* | rejeitada |
| C — ENDOGENOUS EXECUTIVE | inválida | inválida | 0,000* | rejeitada |

`*` Os zeros são agregados brutos do artefato e não constituem score científico quando a linha contém falha operacional. Como B e C não satisfizeram a validade de holdout, `ECG` foi corretamente registrado como `null`, e a Adaptive Recovery Rate agregada não deve ser promovida como resultado comparativo. O gate é `REJECTED_INVALID_EXECUTION`, não `ECG <= 0`.

O único resultado positivo observável foi de mecanismo: em uma tarefa de diagnóstico de C, o modelo produziu `REPRESENT -> DEDUCT -> VERIFY(contradicted) -> DEDUCT -> VERIFY(supported)` em cinco chamadas, sem roteador extra. Isso confirma que o contrato online e o trace de recuperação funcionam na fixture live, mas não fornece evidência de ganho em holdout.

A conclusão é limitada ao modelo, seed, timeout e tarefas desta rodada. A engenharia do controlador endógeno está implementada; a hipótese de ganho executivo permanece sem teste científico válido porque a execução não completou todos os pares necessários. Não se autoriza transferência, novos operadores ou tuning aberto. Qualquer comparação com modelo maior deve repetir exatamente este protocolo em execução separada e somente após autorização explícita.


## Genesis v2-R — Executive Validity Closure

A v2-R é uma etapa de validade operacional, não uma nova arquitetura. O controlador endógeno, as quatro primitivas, o estado acumulativo, a recuperação por feedback e a ausência de roteador extra permanecem congelados. A única alteração é de engenharia: os schemas foram compactados para no máximo 4 entidades, 4 fatos, 4 restrições, 4 incógnitas, 2 hipóteses e 2 previsões, com textos individuais curtos, conclusão de até 96 caracteres e explicação de verificação de até 96 caracteres.

| Elemento | Regra v2-R |
|---|---|
| A — DIRECT | Uma chamada estruturada com teto de 1024 tokens; controle secundário. |
| B — FIXED EXECUTIVE | Até quatro chamadas de 256 tokens, mesmo frame e primitivas; `next_operator` ignorado. |
| C — ENDOGENOUS EXECUTIVE | Até quatro chamadas de 256 tokens, mesmo frame e primitivas; respeita `next_operator` na própria resposta. |
| Budget total B/C | 1024 tokens solicitados por tarefa, sem retries e sem chamada de roteamento. |
| Reparos | `repair_attempts=0`; JSON inválido falha diretamente. |
| Tarefas | Diagnóstico público `reasoning_01`/`reasoning_02`; holdout público `reasoning_06`/`reasoning_07`. |
| Seed/modelo | Seed `42`, `qwen2.5:3b`, gateway local. |
| Escrita | Sem síntese, writeback, promoção, transferência, benchmark privado ou autoedição. |
| Gate | ECG só existe se A, B e C tiverem holdout integralmente válido. |

### Resultado live v2-R

Foi executada uma única rodada live com o protocolo congelado. A condição A terminou validamente nos dois holdouts, embora tenha obtido `0/2`. B e C executaram as quatro decisões disponíveis, mas não terminaram com `verification_supported`; portanto, ambas foram marcadas inválidas por `decision_budget_exceeded`. C teve duas tentativas de recuperação após feedback `contradicted`/`uncertain`, mas nenhuma chegou a `supported` dentro do budget.

| Condição | reasoning_06 | reasoning_07 | Agregado bruto | Validade |
|---|---:|---:|---:|---|
| A — DIRECT | 0/1 | 0/1 | 0,000 | válida |
| B — FIXED EXECUTIVE | inválida | inválida | 0,000* | rejeitada |
| C — ENDOGENOUS EXECUTIVE | inválida | inválida | 0,000* | rejeitada |

`ECG=C−B` foi registrado como `null`, conforme o gate. Os zeros brutos de B/C não são uma comparação científica válida e não devem ser lidos como `C≤B`. O status correto é `REJECTED_INVALID_EXECUTION`, não `NO-GO` por desempenho.

O catálogo local disponível no Windows continha `qwen2.5:3b`, `qwen2.5:0.5b` e `nomic-embed-text`; não havia 7B/8B. Nenhum modelo foi baixado ou substituído automaticamente. Dessa forma, a etapa opcional posterior em 7B/8B permanece bloqueada por disponibilidade e requer autorização/modelo fornecido separadamente; não foi executada.

A v2-R eliminou a hipótese imediata de que o problema era somente JSON truncado em 170 tokens, mas não produziu um A/B/C válido com quatro decisões. O resultado não permite concluir se o controle endógeno supera o fixo. Não se deve acrescentar v2.1, novos operadores ou tuning aberto. A linha permanece parada até eventual execução independente em um modelo 7B/8B disponível.


## Genesis v2-FINAL — Executive Control Gate

A v2-FINAL é o patch experimental final definido após a v2-R. Não introduz arquitetura, operador, memória, solver, síntese, roteador ou capacidade adicional. Ela somente corrige o orçamento que impedia observar a recuperação executiva: B e C recebem o mesmo teto de sete decisões, com 256 tokens solicitados por chamada. O teste final omite A e usa exclusivamente os dois holdouts públicos; a pergunta causal é `ECG = C − B`.

| Elemento | Regra congelada v2-FINAL |
|---|---|
| Condição B | `FIXED EXECUTIVE`, controlador fixo, `next_operator` ignorado |
| Condição C | `ENDOGENOUS EXECUTIVE`, respeita `next_operator` produzido na própria chamada |
| Tarefas | Somente `reasoning_06` e `reasoning_07`, públicas |
| Modelo e seed | `qwen2.5:3b`, gateway Ollama local, seed `42` |
| Budget por tarefa B/C | `7 × 256 = 1792` tokens solicitados |
| Reparos | `repair_attempts=0`; nenhuma chamada escondida |
| Operadores | Somente `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY` |
| Síntese e writeback | Desativados; nenhum resultado é promovido ou usado para calibrar outro resultado |
| Métrica | `ECG = score(C, holdout) − score(B, holdout)` |
| Gate de validade | ECG é `null` se qualquer linha B/C não terminar validamente por `verification_supported` |

### Resultado live v2-FINAL

Foi executada exatamente uma rodada live no modelo local `qwen2.5:3b`, com B/C perfeitamente pareados em seed, modelo, tarefas e budget. As quatro linhas chegaram a sete decisões, mas terminaram por `decision_budget_exceeded` e foram marcadas `VM_ERROR`; portanto, B e C permaneceram inválidas. A execução não foi convertida em score científico zero.

| Condição | reasoning_06 | reasoning_07 | Chamadas/decisões | Agregado bruto | Validade |
|---|---:|---:|---:|---:|---|
| B — FIXED EXECUTIVE | inválida | inválida | 7/7 em cada linha | 0,000* | rejeitada |
| C — ENDOGENOUS EXECUTIVE | inválida | inválida | 7/7 em cada linha | 0,000* | rejeitada |

O resultado registrou duas tentativas de recuperação em C e nenhuma recuperação completa até `supported`. Como as condições não foram válidas, `ECG=C−B` foi corretamente registrado como `null`. O gate operacional é `RUN_7B8_ONCE`: isso não significa `C≤B`, não significa desempenho zero científico e não autoriza uma nova correção no 3B.

O catálogo local Windows foi verificado antes da rodada e continha apenas `qwen2.5:3b`, `qwen2.5:0.5b` e `nomic-embed-text`; nenhum modelo 7B/8B estava instalado. Como o protocolo proíbe download automático e não há modelo maior disponível, a execução única opcional 7B/8B não foi realizada. Assim, a linha Genesis fica encerrada em `REJECTED_INVALID_EXECUTION` no 3B, com o ramo 7B/8B apenas pendente de disponibilidade/autorização, sem base honesta para declarar GO ou NO-GO científico.

`*` Os agregados brutos são mantidos apenas para auditoria do artefato. Linhas inválidas não devem ser interpretadas como comparação de desempenho. Não serão criados Genesis v2.1, novos operadores, tuning de prompt, novas rodadas no 3B ou transferência a partir deste resultado.

A fixture v2-FINAL confirmou o contrato de quatro primitivas, sete decisões e 256 tokens por chamada, mas permanece evidência de engenharia, não de capacidade live.

## Referências

[1]: https://github.com/bugzoidTM/UltronHarness "UltronHarness — repositório público do projeto"

O commit anterior publicado é `331ccd29055ea20a9a61eca6fbf53f7b34661378`. A publicação desta versão e os gates de validação são registrados no histórico público do repositório [UltronHarness](https://github.com/bugzoidTM/UltronHarness).


## Auditoria offline pós-v2-FINAL

A validade de execução e a performance da tarefa são dimensões distintas. Por isso, o pós-processamento autorizado do JSON bruto v2-FINAL deve separar:

```text
ECG-task = external_score(C) - external_score(B)
ECG-self = self_termination(C) - self_termination(B)
```

`ECG-task` avalia, com o verificador público já existente, o último `candidate_answer` explicitamente serializado em cada linha B/C, mesmo que a VM tenha terminado por `decision_budget_exceeded`. `ECG-self` mede a fração de linhas que terminaram com `verification_supported`. Uma linha sem candidato explícito não pode ser convertida em score zero nem reconstruída a partir de `candidate_present`; nesse caso, a acurácia externa e `ECG-task` permanecem `null`.

O auditor [`scripts/audit_genesis_v2final.py`](scripts/audit_genesis_v2final.py) não chama modelos, não cria seeds, não faz tuning, não acessa private/unseen, não envia holdout a sintetizador e não faz writeback. Ele exige exatamente quatro linhas pareadas (`generic_closed_loop_v2final` e `endogenous_executive_v2final` para `reasoning_06` e `reasoning_07`), sete decisões, 256 tokens por chamada, 1792 tokens por tarefa e metadados pareados.

### Resultado da auditoria do JSON live v2-FINAL

No JSON bruto existente, as quatro linhas possuem `response=""` e não serializam o valor de `candidate_answer`; os traces preservam somente a presença booleana e o estado textual. O auditor encontrou:

| Métrica | B — FIXED EXECUTIVE | C — ENDOGENOUS EXECUTIVE |
|---|---:|---:|
| Cobertura de candidate explícito | 0/2 | 0/2 |
| `external_accuracy` | `null` | `null` |
| `verification_supported` | 0/2 | 0/2 |
| Recovery attempts | 0 | 2 |
| Recovery completed | 0 | 0 |
| Média de decisões | 7 | 7 |

Assim, `ECG-task=null` e `ECG-self=0,000`. O resultado da auditoria é **`AUDIT_INCONCLUSIVE_MISSING_CANDIDATE_ANSWER`**. B terminou com a sequência `REPRESENT → HYPOTHESIZE → HYPOTHESIZE → DEDUCT → VERIFY → HYPOTHESIZE → HYPOTHESIZE` em `reasoning_06` e `REPRESENT → HYPOTHESIZE → DEDUCT → VERIFY → DEDUCT → VERIFY → DEDUCT` em `reasoning_07`. C teve `contradicted` como último status de verificação observável em `reasoning_06` e `uncertain` em `reasoning_07`, mas nenhum candidato foi preservado para avaliação externa.

Esse resultado é uma falha de observabilidade do artefato, não evidência de `C≤B`, `C=B` ou `C>B`. A auditoria não justifica uma nova execução 7B/8B nem uma conclusão de capacidade, porque o JSON não permite distinguir candidato correto de candidato incorreto ausente. Qualquer execução futura que pretenda medir `ECG-task` deve serializar explicitamente o último `candidate_answer` antes de marcar uma linha inválida, sem usar inferência retrospectiva.
