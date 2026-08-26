# Project Genesis v0.2.2 — Non-Solving Cognitive Virtual Machine

## Resumo executivo

O Genesis v0.2.2 remove a semântica solucionadora que havia sido identificada na v0.2. A VM ativa contém somente quatro operadores de controle cognitivo — `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY` — e cada operador solicita ao mesmo modelo uma saída estruturada. Nenhuma primitiva calcula respostas em Python ou conhece a família da tarefa.

O protocolo compara DIRECT, MATCHED COMPUTE e SELF-GENERATED PROGRAM com orçamento solicitado total pareado por tarefa. A métrica primária é `Δ(C−B)`, pois B controla o efeito de fazer quatro chamadas em vez de uma. O diagnóstico público continua separado dos dois holdouts públicos; não há writeback, transferência ou autoedição.

> Conclusão honesta: no único probe live v0.2.2, A=0,000, B=0,500 e C=0,000, portanto `Δ(C−B)=-0,500`. O resultado não demonstra ganho além de compute extra e não sustenta alegações de ganho cognitivo estrutural ou AGI. Os resultados v0.2 e v0.2.1 abaixo permanecem como histórico e justificativa da correção.

## Histórico: o que mudou em relação ao Genesis v0.1

No v0.1, os operadores eram serializados como texto no prompt e o modelo era instruído a “seguir” a sequência. No v0.2, a sequência é executada antes da chamada do executor, e cada operador possui uma transformação definida no estado.

| Aspecto | Genesis v0.1 | Genesis v0.2 |
|---|---|---|
| Execução | Sequência textual no prompt | Interpretação pela Cognitive VM |
| Estado | Implícito no modelo | `CognitiveFrame` persistido em memória de execução |
| Operadores | 13, incluindo `STOP` | 6, sem `STOP` |
| Repetição | Rejeitada | Permitida |
| Rationale | Entrava no prompt | Metadado de auditoria בלבד; não operacional |
| Verificação pública | Substring | Igualdade exata |
| Programas | Até 3 | Até 2 |
| Tarefas | 2 diagnóstico + 2 holdout | 2 diagnóstico + 2 holdout |

## Protocolo histórico congelado do Genesis v0.2

| Item | Regra implementada |
|---|---|
| Diagnóstico | `reasoning_01` e `reasoning_02`, públicas. |
| Holdout | `reasoning_06` e `reasoning_07`, públicas e não enviadas ao sintetizador. |
| Programas | De 1 a 2 programas gerados pelo modelo; nenhum catálogo fechado. |
| Operadores | `REPRESENT`, `DECOMPOSE`, `HYPOTHESIZE`, `DEDUCT`, `VERIFY`, `BACKTRACK`. |
| Limite | De 1 a 4 operadores; operadores podem se repetir. `STOP` não existe no schema. |
| Estado | `problem`, `facts`, `unknowns`, `constraints`, `hypotheses`, `predictions`, `candidate_answer`, `verification` e `trace`. |
| Modelo | Mesmo modelo efetivo em síntese, baseline e candidate; nome registrado por execução. |
| Seed | Uma seed fixa, `42`; não há múltiplas seeds. |
| Budget | Mesmo `max_tokens`, timeout, allowlist, limite de passos e fingerprint de tarefa nas condições pareadas. |
| Execução | 2 baseline diagnóstico + até 4 candidate diagnóstico + 2 baseline holdout + 2 candidate holdout = máximo de 10 execuções. |
| Tempo | Timeout global configurável, limitado a 600 segundos; default 540 segundos. |
| Leakage | O sintetizador recebe apenas observações do diagnóstico. O holdout e seu resultado não são transmitidos ao sintetizador. |
| Rationale | Não aparece nas mensagens do executor, não é interpretado pela VM e não influencia o score. |
| Segurança | Nenhum operador executa Python, shell, Git, rede, escrita de arquivo, permissão ou autoedição. |
| Seleção | Média diagnóstica com desempate determinístico pela ordem de geração; não existe argumento humano de seleção. |
| Verificador | Resposta deve ser exatamente o resultado derivado da fórmula pública. |
| Promoção | NCPG positivo, ausência de regressão, VM válida, evidência suficiente e `VerifiedWritebackGate`. |

O protocolo está em [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md).

## Implementação

O schema [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py) define `CognitiveProgram`, `CognitiveProgramBatch`, `CognitiveFrame` e `GenesisSummary`. A validação aceita somente os seis operadores da VM, permite repetição, rejeita `STOP` e mantém o limite de quatro operadores.

A VM em [`ultron/genesis/vm.py`](ultron/genesis/vm.py) possui contratos operacionais mínimos. `REPRESENT` registra o problema e restrições; `DECOMPOSE` extrai componentes; `HYPOTHESIZE` registra uma relação e previsão; `DEDUCT` produz conclusão para as formas públicas suportadas; `VERIFY` registra verificação; e `BACKTRACK` registra reconsideração sem ação externa. Cada passo gera um item de trace.

O runner em [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py) executa a VM no candidate e passa ao modelo somente o `CognitiveFrame` resultante. O `rationale` não é referenciado nas mensagens de execução. O runner nunca carrega `benchmark_private`; seu verificador usa somente fórmulas derivadas dos quatro enunciados públicos congelados e exige `actual == expected`.

O controlador em [`ultron/genesis/controller.py`](ultron/genesis/controller.py) mantém seleção, holdout, paridade, NCPG e `VerifiedWritebackGate`. A retenção da experiência continua separada de reuso procedural amplo: a assinatura é marcada como verificada, mas o limiar existente de reuso não é relaxado.

## Resultado histórico do probe live v0.2

O ambiente Windows conectado forneceu o mesmo modelo local `qwen2.5:3b` para a síntese e para todas as execuções. O modelo gerou um programa único, `CP-01`, com a sequência:

```text
REPRESENT -> DECOMPOSE -> HYPOTHESIZE -> DEDUCT
```

A sequência foi interpretada pela VM. O diagnóstico foi enviado ao sintetizador; o holdout permaneceu fora do contexto de síntese. O `rationale_used_for_execution` registrado foi `false` e `human_selected_program` foi `false`.

| Campo | Resultado |
|---|---:|
| Uso | `bounded_exploratory` |
| Modelo | `qwen2.5:3b` |
| Seed | `42` |
| `max_tokens` | `1024` |
| Programas gerados | 1 |
| Programa selecionado | `CP-01` |
| Execuções de tarefa | 8 |
| Baseline holdout | 0,500 — 1/2 |
| VM candidate holdout | 1,000 — 2/2 |
| NCPG | `+0,500` |
| Status | `promoted` |
| Writeback | permitido pelo `VerifiedWritebackGate` |
| Reuso amplo imediato | `false` |

A contagem de oito execuções é compatível com um único programa: duas baseline de diagnóstico, duas candidate de diagnóstico, duas baseline de holdout e duas candidate de holdout. O experimento não foi aumentado depois de observar o resultado.

Os fingerprints das tarefas holdout foram iguais entre baseline e candidate. O modelo e a seed foram `qwen2.5:3b` e `42` em todos os pares; a allowlist permaneceu vazia. A evidência pública foi registrada como `derived_formula` e `exact_match`.

O programa live selecionado foi `CP-01`, gerado pelo modelo, com a sequência `REPRESENT -> DECOMPOSE -> HYPOTHESIZE -> DEDUCT`. A VM executou quatro transformações de estado por tarefa candidate; o `rationale` longo associado ao programa não entrou na mensagem do executor. O programa não incluiu `VERIFY`, portanto este resultado não demonstra a cadeia completa de verificação proposta: demonstra especificamente a execução de representação, decomposição, hipótese e dedução dentro do contrato atual da VM.

O baseline holdout acertou `reasoning_07` e falhou `reasoning_06`; o candidate com CP-01 acertou os dois. Assim, o NCPG foi `0,500` (`1,000 - 0,500`) em duas tarefas, com oito execuções totais porque apenas um programa foi gerado. O holdout permaneceu ausente do prompt de síntese, e o relatório registrou `rationale_used_for_execution=false` e `human_selected_program=false`.

## Histórico Genesis v0.2.1 — No-Answer Ablation

A v0.2.1 foi executada como uma ablação A/B/C estritamente bounded para separar a estrutura intermediária do conteúdo calculado deterministamente pela VM. O CP-01 foi congelado exatamente como no probe anterior (`REPRESENT -> DECOMPOSE -> HYPOTHESIZE -> DEDUCT`), sem nova síntese, seleção humana ou writeback. Foram usadas exatamente as duas tarefas holdout públicas `reasoning_06` e `reasoning_07`, com seis chamadas totais.

| Condição | reasoning_06 | reasoning_07 | Score médio |
|---|---:|---:|---:|
| A — baseline | 0/1 | 1/1 | 0,500 |
| B — VM sem `candidate_answer` | 0/1 | 1/1 | 0,500 |
| C — VM com frame completo | 1/1 | 1/1 | 1,000 |

O ambiente Windows conectado usou `qwen2.5:3b`, seed `42`, `max_tokens=1024`, a mesma configuração pareada e os mesmos fingerprints de tarefa. O resultado foi `Δ(B−A)=0,000` e `Δ(C−A)=+0,500`. Em B, o executor recebeu somente `facts`, `unknowns`, `constraints`, `hypotheses` e `predictions`; `candidate_answer`, `verification`, `trace` e `rationale` não foram serializados. Em C, o frame completo foi enviado. A telemetria registrou `vm_valid=true` em todas as execuções, `vm_steps=0` em A e `vm_steps=4` em B/C.

Os invariantes de desenho foram `rationale_used_for_execution=false`, `synthesis_performed=false` e `writeback_performed=false`. A condição B não reproduziu o ganho de C sobre A, enquanto C repetiu o ganho observado no v0.2. Isso é consistente com a hipótese de que o ganho anterior dependeu do `candidate_answer` (ou de conteúdo correlato do frame completo) fornecido pelo solver, e não apenas dos campos intermediários. A evidência não prova causalidade geral: o n é duas tarefas, há uma única seed, uma família de modelo e um programa congelado. Por isso, o resultado bloqueia transferência e exige correção semântica da VM antes de atribuir capacidade ao estado intermediário.

A fixture determinística A/B/C valida apenas serialização, paridade e ausência de síntese/writeback; não é evidência de capacidade. Nenhuma condição da ablação v0.2.1 foi promovida ou escreveu experiência.

## Interpretação e decisão

O resultado live v0.2 original permanece válido como histórico do comportamento observado: um único CP-01 produziu baseline holdout `0,500` e candidate `1,000`. A nova ablação, porém, restringe a interpretação desse ganho. O próprio `DEDUCT` contém semântica determinística para as formas públicas utilizadas; portanto, o frame completo pode ter funcionado como uma resposta calculada, e não como uma representação intermediária que o modelo precisou transformar em solução.

A conclusão operacional é **não prosseguir para transferência, Genesis v0.3 ou alegações de autoaperfeiçoamento** nesta linha. O próximo trabalho autorizado deve primeiro revisar a semântica e o contrato de execução da VM para eliminar a exposição de respostas prontas, seguido de um protocolo novo e explicitamente pré-registrado. O resultado atual não autoriza alegações de descoberta de algoritmo geral, generalização estatística, consciência ou dinâmica de desenvolvimento comparável à AGI.

## Testes e gates históricos v0.2.1

| Verificação | Resultado |
|---|---:|
| Testes Genesis direcionados + ablação | 15 passed |
| Ruff em código e testes alterados | aprovado |
| Fixture A/B/C de mecânica | A=0,500; B=0,500; C=1,000; desenvolvimento-only |
| Suíte completa Linux | 246 passed, 1 warning |
| Segurança Windows | 12 passed, 1 skipped, 1 warning |
| Repetição de operadores | coberta |
| `STOP` rejeitado | coberto |
| VM exige representação antes de dedução | coberto |
| VM altera `CognitiveFrame` passo a passo | coberto |
| Rationale fora da execução | coberto |
| Verificador substring `153` para resposta `53` | rejeitado |
| Seleção humana intermediária | não permitida pela assinatura |
| Divergência de modelo/seed/fingerprint | rejeitada |
| Benchmark privado/unseen | não executado |
| Múltiplas seeds | não executadas |
| Execução de código gerado | proibida e não executada |

## Limitações e segurança

O Genesis v0.2 continua opt-in e desligado por padrão. Os operadores não têm acesso a ferramentas externas e não modificam o repositório ou o runtime. O `rationale` pode ser guardado para auditoria, mas não é um canal operacional. O writeback usa as autoridades existentes e não cria uma permissão especial para programas Genesis.

O runner público foi mantido separado do runner geral precisamente para impedir que o ciclo Genesis consulte `benchmark_private`. Nenhum gold, expected output privado, fixture privada ou conteúdo unseen foi copiado para o código público ou para os artefatos de entrega.

A fixture determinística confirma a implementação do mecanismo, mas não confirma descoberta pelo modelo. Os probes live v0.2 e v0.2.1 são exploratórios e insuficientes para uma conclusão científica geral; o resultado A/B/C foi registrado integralmente, sem seleção retrospectiva de casos favoráveis.

## Arquivos

| Arquivo | Função |
|---|---|
| [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md) | Protocolo Genesis v0.2 Cognitive VM e ablação No-Answer v0.2.1. |
| [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py) | CognitiveFrame, CognitiveProgram e contratos. |
| [`ultron/genesis/vm.py`](ultron/genesis/vm.py) | VM não solucionadora dos quatro operadores estruturados v0.2.2. |
| [`ultron/genesis/synthesizer.py`](ultron/genesis/synthesizer.py) | Síntese estruturada das quatro primitivas não solucionadoras. |
| [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py) | Runner público DIRECT/MATCHED COMPUTE/PROGRAM com orçamento pareado. |
| [`ultron/genesis/controller.py`](ultron/genesis/controller.py) | Seleção, holdout, gates, writeback histórico e budget explícito. |
| [`scripts/run_genesis_v022.py`](scripts/run_genesis_v022.py) | Probe fixture/live do protocolo v0.2.2. |
| [`scripts/run_genesis_probe.py`](scripts/run_genesis_probe.py) | Wrapper histórico para o probe v0.2.2. |
| [`scripts/run_genesis_ablation.py`](scripts/run_genesis_ablation.py) | Wrapper histórico para o probe v0.2.2. |
| [`tests/test_genesis.py`](tests/test_genesis.py) | Testes de semântica, autoria, paridade e isolamento. |
| [`tests/test_genesis_ablation.py`](tests/test_genesis_ablation.py) | Testes de operadores estruturados, paridade de compute e ausência de solver. |

## Genesis v0.2.2 — Non-Solving Cognitive VM

A v0.2.2 substitui a VM solver do v0.2 por quatro operadores que não conhecem a semântica das tarefas: `REPRESENT`, `HYPOTHESIZE`, `DEDUCT` e `VERIFY`. Cada operador chama o mesmo gateway/modelo com saída estruturada. `REPRESENT` produz entidades, fatos, restrições e incógnitas; `HYPOTHESIZE` produz hipóteses e previsões; `DEDUCT` produz uma conclusão textual por chamada do modelo; e `VERIFY` classifica a conclusão. O arquivo da VM não contém regex, aritmética, reconhecimento de família de benchmark ou gabarito. O verificador público continua separado e usa apenas o enunciado para avaliar a resposta, não para gerar o estado cognitivo.

O probe [`scripts/run_genesis_v022.py`](scripts/run_genesis_v022.py) mantém o diagnóstico público `reasoning_01`/`reasoning_02` e o holdout público `reasoning_06`/`reasoning_07`. A condição A faz uma chamada estruturada com orçamento solicitado de 1024 tokens; B faz quatro chamadas genéricas de 256 tokens; C faz quatro chamadas de 256 tokens organizadas pelo programa sintetizado. A métrica primária é `Δ(C−B)`, e `Δ(C−A)` é secundária. Não há writeback, promoção, transferência ou alteração automática do código.

## Resultado live v0.2.2

A única execução live válida foi realizada no Windows conectado com `qwen2.5:3b`, seed `42`, orçamento solicitado total de 1024 tokens por tarefa e timeout global de 540 segundos. O sintetizador gerou dois programas, ambos com as quatro primitivas, e a seleção automática pelo diagnóstico escolheu `CP-02`:

```text
REPRESENT -> HYPOTHESIZE -> DEDUCT -> VERIFY
```

O resultado nos dois holdouts públicos foi:

| Condição | reasoning_06 | reasoning_07 | Score médio |
|---|---:|---:|---:|
| A — DIRECT | 0/1 | 0/1 | 0,000 |
| B — MATCHED COMPUTE | 0/1 | 1/1 | 0,500 |
| C — SELF-GENERATED PROGRAM (`CP-02`) | 0/1 | 0/1 | 0,000 |

Assim, `Δ(C−B)=-0,500` e `Δ(C−A)=0,000`. Todas as linhas utilizaram o mesmo modelo efetivo (`qwen2.5:3b`), seed `42`, configuração e fingerprints de tarefa. A registrou uma chamada e C registrou quatro chamadas por tarefa; C teve quatro passos VM válidos quando concluiu, mas não acertou nenhum holdout. O holdout não foi enviado ao sintetizador, `rationale_used_for_execution=false` e `writeback_performed=false`.

O resultado é **negativo para a hipótese deste microprobe**: não há sinal de que a organização autogerada tenha superado quatro chamadas genéricas com o orçamento solicitado pareado. Isso não prova que nenhuma organização possa funcionar; mostra apenas que esta síntese, nesta seed, neste modelo e nestas duas tarefas não produziu `C > B`. Também não é apropriado atribuir o resultado a uma única causa, porque A, B e C têm prompts e schemas diferentes além da organização. A conclusão operacional é não iniciar transferência nem tratar a VM como ganho arquitetural demonstrado.

A fixture do v0.2.2 continua sendo somente teste de mecanismo. Os programas gerados, as respostas por tarefa, os fingerprints e os invariantes completos estão no JSON raw do probe; o arquivo não é incluído no commit público como dado gerado.

## Decisão atual

O Genesis v0.2.2 cumpre o objetivo de remover o solver determinístico da VM e medir explicitamente `C−B`, mas o resultado live não suporta a hipótese de ganho além de compute extra. A linha deve permanecer parada para análise de desenho e calibração experimental. Não devem ser adicionados memória nova, multiagente, recombinação, transferência, autoedição, novos operadores ou novos benchmarks com base neste resultado.

## Validação final da v0.2.2

| Gate | Resultado |
|---|---:|
| Testes Genesis e v0.2.2 direcionados | 13 passed |
| Ruff em `ultron/genesis`, `scripts` e testes alterados | aprovado |
| Suíte completa Linux com `ULTRON_VECTOR_ENABLED=false` | 244 passed, 1 warning |
| Testes de segurança Windows | 12 passed, 1 skipped, 1 warning |
| Fixtures dos três entrypoints (`run_genesis_v022`, `run_genesis_probe`, `run_genesis_ablation`) | executadas com sucesso |
| Solver de domínio na VM | ausente; teste de fonte aprovado |
| Benchmark privado, unseen e novas famílias | não executados |
| Writeback e transferência | não executados |

Os arquivos novos ou modificados para a v0.2.2 são [`scripts/run_genesis_v022.py`](scripts/run_genesis_v022.py), os wrappers históricos [`scripts/run_genesis_probe.py`](scripts/run_genesis_probe.py) e [`scripts/run_genesis_ablation.py`](scripts/run_genesis_ablation.py), os schemas estruturados em [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py), a VM em [`ultron/genesis/vm.py`](ultron/genesis/vm.py), o runner em [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py), o sintetizador em [`ultron/genesis/synthesizer.py`](ultron/genesis/synthesizer.py), o controlador com budget explícito em [`ultron/genesis/controller.py`](ultron/genesis/controller.py), as exportações do pacote e os testes correspondentes. O JSON raw live permanece fora do commit por ser dado gerado do experimento.
