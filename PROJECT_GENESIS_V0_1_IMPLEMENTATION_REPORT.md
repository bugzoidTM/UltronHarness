# Project Genesis v0.2 — Cognitive Virtual Machine

## Resumo executivo

O Genesis v0.2 substitui a execução textual do Genesis v0.1 por uma **Cognitive Virtual Machine (VM)** bounded. O modelo gera uma sequência de operadores; a VM interpreta cada operador sobre um `CognitiveFrame` explícito, registra a transformação de estado e termina quando a sequência acaba ou o budget da VM é atingido. O `rationale` continua preservado para auditoria, mas não entra no prompt do executor e não é lido pela VM.

O ciclo cobre duas tarefas públicas de diagnóstico, síntese de no máximo dois programas, seleção automática, duas tarefas públicas holdout e writeback somente após NCPG positivo, execução VM válida, paridade contratual e autoridade final. O verificador público foi fechado para igualdade exata, eliminando aceitação por substring.

> Conclusão honesta: o probe live demonstrou uma sequência gerada pelo próprio modelo sendo interpretada pela VM e associada a ganho neste microprobe público. Isso é evidência exploratória de um mecanismo de engenharia. Não é evidência de AGI, algoritmo cognitivo geral, transferência ampla ou autoaperfeiçoamento aberto.

## O que mudou em relação ao Genesis v0.1

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

## Protocolo congelado

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

## Resultado do probe live

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

## Interpretação

O resultado é compatível com a hipótese operacional de que uma sequência de operadores criada pelo modelo pode produzir um estado intermediário útil para a chamada candidate e melhorar o desempenho em duas tarefas públicas holdout. Contudo, o microprobe é pequeno, usa uma única seed, uma única família pública e duas tarefas holdout. O próprio `DEDUCT` contém semântica determinística para as formas de tarefa públicas utilizadas; isso é uma VM verificável, não uma teoria geral de raciocínio.

Além disso, o baseline obteve sucesso em uma das duas tarefas holdout. O NCPG positivo mede diferença neste par específico, não uma taxa geral de capacidade. O resultado não separa completamente a contribuição da VM da contribuição do fato de o `CognitiveFrame` expor `candidate_answer` ao executor. Essa questão deve permanecer aberta para um protocolo posterior de ablação, sem alterar este resultado retrospectivamente.

O resultado live não autoriza alegações de descoberta de algoritmo geral, transferência para outra família, generalização estatística, consciência ou dinâmica de desenvolvimento comparável à AGI. O próximo teste científico, se autorizado, deve congelar uma superfície diferente antes da execução e verificar se a mesma sequência continua útil sem ser ajustada ao novo domínio.

## Testes e gates

| Verificação | Resultado |
|---|---:|
| Testes Genesis direcionados | 11 passed |
| Ruff em código e testes alterados | aprovado |
| Suíte completa | a executar após o último conjunto de alterações |
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

A fixture determinística confirma a implementação do mecanismo, mas não confirma descoberta pelo modelo. O probe live, por sua vez, é exploratório e positivo, porém insuficiente para uma conclusão científica geral. Um resultado negativo ou positivo futuro deve ser registrado integralmente, sem seleção retrospectiva de casos favoráveis.

## Arquivos

| Arquivo | Função |
|---|---|
| [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md) | Protocolo Genesis v0.2 Cognitive VM. |
| [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py) | CognitiveFrame, CognitiveProgram e contratos. |
| [`ultron/genesis/vm.py`](ultron/genesis/vm.py) | Interpretador bounded dos seis operadores. |
| [`ultron/genesis/synthesizer.py`](ultron/genesis/synthesizer.py) | Síntese estruturada de sequências VM. |
| [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py) | VM, modelo e verificador exclusivamente públicos. |
| [`ultron/genesis/controller.py`](ultron/genesis/controller.py) | Seleção, holdout, gates e writeback. |
| [`scripts/run_genesis_probe.py`](scripts/run_genesis_probe.py) | Probe fixture/live. |
| [`tests/test_genesis.py`](tests/test_genesis.py) | Testes de semântica, autoria, paridade e isolamento. |
