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
