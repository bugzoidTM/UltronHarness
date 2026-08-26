# Project Genesis v0.1 — Cognitive Programs

## Resumo executivo

O Project Genesis v0.1 foi implementado como um experimento bounded de composição de programas cognitivos temporários. O sistema oferece somente uma lista fechada de primitivas interpretáveis; a sequência que combina essas primitivas é gerada por uma chamada estruturada do modelo, não por uma tabela de estratégias escrita no controlador. O programa gerado não é código e não pode executar Python, shell, Git, rede, escrita de arquivos ou alteração de permissões.

A implementação cobre diagnóstico público, síntese de até três programas, avaliação automática no diagnóstico, seleção determinística sem parâmetro humano, holdout público separado, validação de paridade e writeback canônico. O modo fixture passou o encadeamento completo. O único probe live exploratório com `qwen2.5:3b` foi rejeitado antes da execução de tarefas porque o modelo produziu programas estruturalmente inválidos, sem `STOP` terminal dentro do limite de seis operadores. Essa rejeição é o resultado correto do gate e não foi convertida artificialmente em ganho.

> Conclusão honesta: o Genesis v0.1 demonstra um mecanismo de geração, validação, seleção e retenção bounded. O probe live ainda não demonstrou que o modelo inventa um programa válido que melhora o desempenho em holdout.

## Protocolo congelado

| Item | Regra implementada |
|---|---|
| Diagnóstico | `reasoning_01` e `reasoning_02`, ambas públicas. |
| Holdout | `reasoning_06` e `reasoning_07`, ambas públicas e não enviadas ao sintetizador. |
| Programas | 1 a 3 programas por síntese, sem catálogo de estratégias. |
| Operadores | Lista pública de 13 primitivas; cada programa tem 1 a 6 operadores e `STOP` obrigatório na última posição. |
| Orçamento | Mesmo modelo efetivo, seed, `max_tokens`, timeout, allowlist e limite de passos em todas as condições. |
| Seleção | Média diagnóstica; desempate pela ordem de geração. Nenhum argumento `selected_program_id` é aceito. |
| Execuções | 2 baseline diagnóstico + até 6 candidatos diagnóstico + 2 baseline holdout + 2 vencedor holdout = máximo de 12 tarefas. |
| Tempo | Timeout total configurável, limitado a 600 segundos; default de 540 segundos. |
| Leakage | O sintetizador recebe somente objetivos, respostas e falhas genéricas do diagnóstico. O holdout não é transmitido. |
| Segurança | Programas são sequências textuais validadas por Pydantic e nunca são executados como código. |
| Promoção | NCPG positivo, ausência de regressão, evidência suficiente e `OutcomeAuthority` final são necessários para `VerifiedWritebackGate`. |

O protocolo completo está em [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md).

## Implementação

O schema [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py) define `CognitiveProgram`, `CognitiveProgramBatch` e `GenesisSummary`. A validação rejeita operadores fora da lista, IDs inválidos, operadores repetidos, `STOP` não terminal e programas que excedam o orçamento. Nenhuma operação é inserida automaticamente no programa recebido; em particular, um output sem `STOP` é rejeitado em vez de ser corrigido pelo controlador.

O sintetizador [`ultron/genesis/synthesizer.py`](ultron/genesis/synthesizer.py) usa a saída estruturada do mesmo gateway/modelo configurado para o experimento. O prompt inclui apenas as observações do diagnóstico e as primitivas permitidas. O holdout não aparece no prompt, na lista de mensagens ou no contexto do sintetizador.

O runner [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py) é separado do runner UGIB-Lite geral para não carregar o diretório `benchmark_private`. Seu verificador deriva as respostas somente dos quatro enunciados públicos congelados e registra evidência genérica, sem retornar gabarito ao modelo. As execuções são persistidas nas tabelas públicas de research e o envelope do experimento é persistido em `experiments`.

O controlador [`ultron/genesis/controller.py`](ultron/genesis/controller.py) executa o ciclo completo. Ele escolhe o vencedor automaticamente com base apenas no diagnóstico, executa o holdout depois da seleção, compara pares pelo mesmo fingerprint de tarefa e exige paridade de modelo, seed e configuração. Em caso de ganho válido, a experiência recebe assinatura verificável e passa pelo `VerifiedWritebackGate`; a retenção não é confundida com reuso validado, que continua sujeito aos limiares já existentes.

## Resultados de validação

### Fixture determinística

| Campo | Resultado |
|---|---:|
| Uso | `development_only` |
| Programas gerados | `CP-ALPHA`, `CP-BETA`, `CP-GAMMA` |
| Programa selecionado | `CP-BETA` |
| Execuções | 12 |
| Baseline holdout | 0,000 |
| Programa selecionado holdout | 1,000 |
| NCPG | +1,000 |
| Status | `promoted` |
| Writeback | permitido pelo `VerifiedWritebackGate` |
| Reuso imediato | `false` — retenção não equivale ao limiar de reuso |

A fixture foi construída para verificar o encadeamento de controle e define explicitamente o resultado por condição. Portanto, seu NCPG não é uma medida de inteligência nem evidência sobre o modelo.

### Probe live exploratório

O ambiente Windows conectado confirmou a disponibilidade de `qwen2.5:3b`. O probe usou o mesmo modelo local para síntese e tarefas, uma seed `42`, `max_tokens=1024`, timeout bounded e os quatro IDs públicos do protocolo. O modelo retornou três objetos com sequências de operadores sem `STOP` dentro do máximo de seis posições. O schema rejeitou os três com `stop_required_last` ou `stop_exceeds_operator_budget`, antes de diagnóstico/candidate/holdout.

| Campo | Resultado |
|---|---:|
| Uso | `bounded_exploratory` |
| Modelo | `qwen2.5:3b` via perfil `ollama_research` |
| Status | `rejected` |
| Motivo | `execution_error:ValidationError` na síntese estruturada |
| Tarefas executadas | 0 |
| Writeback | nenhum |
| Holdout consultado | não |
| Benchmark privado consultado | não |

A falha live é informativa sobre aderência do modelo ao contrato de programa, mas não permite concluir que o modelo não consiga gerar programas válidos em outros prompts ou budgets. Também não permite concluir que existe NCPG positivo.

### Testes automatizados

| Verificação | Resultado |
|---|---:|
| Ruff em Genesis, probe e testes | aprovado |
| Testes Genesis direcionados | 9 passed |
| Suíte completa | 240 passed, 1 warning |
| Múltiplas seeds | não executadas |
| Benchmark privado/unseen | não executado |
| Execução de código gerado | proibida e não executada |

A suíte completa foi executada com `ULTRON_VECTOR_ENABLED=false`, somente para neutralizar uma diferença ambiental do serviço de embeddings no sandbox e manter o teste preexistente de retrieval determinístico. Essa variável não altera o protocolo Genesis.

## Limitações científicas

O modo fixture não prova descoberta de algoritmo. O modo live terminou na validação de schema e não chegou ao holdout. O experimento tem somente duas tarefas de diagnóstico e duas de holdout, uma seed e uma família pública pequena. Não há replicação estatística, avaliação independente, transferência para uma família nova ou recombinação entre programas.

Um eventual NCPG positivo em uma futura execução live ainda seria evidência exploratória. Para uma conclusão mais forte, seria necessário congelar um protocolo confirmatório antes da execução, repetir seeds, manter holdouts verdadeiramente independentes e impedir qualquer tuning após observar os resultados. Nenhuma etapa posterior deve transformar um passe de fixture em alegação de AGI.

## Arquivos

| Arquivo | Função |
|---|---|
| [`GENESIS_V0_1_PROTOCOL.md`](GENESIS_V0_1_PROTOCOL.md) | Protocolo bounded congelado. |
| [`ultron/genesis/schemas.py`](ultron/genesis/schemas.py) | Contratos e lista de primitivas. |
| [`ultron/genesis/synthesizer.py`](ultron/genesis/synthesizer.py) | Síntese estruturada sem catálogo fechado. |
| [`ultron/genesis/public_runner.py`](ultron/genesis/public_runner.py) | Execução e verificação exclusivamente públicas. |
| [`ultron/genesis/controller.py`](ultron/genesis/controller.py) | Seleção, holdout, gates e writeback. |
| [`scripts/run_genesis_probe.py`](scripts/run_genesis_probe.py) | Probe `fixture` e `live`. |
| [`tests/test_genesis.py`](tests/test_genesis.py) | Testes de integridade e adversariais. |

O resultado bruto do fixture foi produzido em diretório temporário. O resultado live foi mantido apenas como artefato exploratório local; nenhum contrato privado, gold ou conteúdo unseen foi copiado para o repositório público.
