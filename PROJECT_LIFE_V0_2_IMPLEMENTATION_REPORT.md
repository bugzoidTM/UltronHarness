# Project LIFE v0.2 — Self Directed Capability Gain

## Resumo executivo

O LIFE v0.2 implementa e valida um único mecanismo bounded de autoaperfeiçoamento comportamental: uma lacuna de competência empiricamente persistida é detectada pelo self model, o LIFE seleciona uma investigação, deriva uma única hipótese de estratégia, compara baseline e candidate em três microtarefas públicas pareadas e só promove a estratégia depois de um ganho verificado por autoridade registrada.

O microprobe executado foi determinístico e baseado em fixture pública. Ele passou todos os gates internos: seis execuções no total, mesma seed, mesmo modelo nominal, mesmo contrato de tarefa, mesma allowlist, mesmo timeout, sem resultado baseline entregue ao candidate, ganho positivo, dois writebacks autorizados e reuso procedural habilitado. A interpretação correta é limitada: o resultado demonstra que o encadeamento de engenharia funciona na fixture. Não demonstra AGI, vontade forte, generalização, transferência, lift científico ou autoaperfeiçoamento geral.

## Resultado do microprobe

| Campo | Resultado |
|---|---:|
| Protocolo | `life-sdcg-v0.2` |
| Uso científico | `development_only` |
| Lacuna detectada | `COMPETENCE_GAP` em `reasoning/representation` |
| Hipóteses formuladas | 1 |
| Tarefas públicas | `reasoning_06`, `reasoning_07`, `reasoning_08` |
| Execuções | 6 |
| Seed | 42 |
| Modelo da fixture | `local-fallback` |
| Baseline médio | 0,000 |
| Candidate médio | 1,000 |
| SDCG | +1,000 |
| Status | `promoted` |
| Reuso procedural | `true` |

A fixture determinística retorna uma condição baseline malsucedida e uma condição candidate bem sucedida quando a intervenção comportamental está presente. Por isso, o valor numérico do ganho não deve ser lido como desempenho de modelo ou medida de capacidade real. O valor do probe está em verificar, de forma rápida e reproduzível, que as condições de seleção, pareamento, validação, autoridade e promoção são realmente aplicadas.

## Mecanismo implementado

A entrada do mecanismo é a tabela canônica `capability_estimates`. A detecção utiliza exclusivamente estimativas com tamanho amostral mínimo e taxa de sucesso abaixo do limiar configurado. Quando existem várias lacunas, a ordenação determinística já usada pelo LIFE seleciona uma única tensão. O v0.2 não cria outro self model nem cria um novo motor cognitivo.

A hipótese é derivada pelo próprio controlador LIFE a partir de `domain` e `task_type` da evidência da lacuna. Para a fixture utilizada, `task_type=representation` produz a hipótese de que uma representação explícita do estado inicial, da transformação ou restrição principal e do estado desejado, seguida de verificação de consistência e formato, pode reduzir erros. A implementação registra `selection_source=life_gap_policy`; não existe argumento de API para uma pessoa fornecer ou escolher a estratégia intermediária.

A estratégia é um gene comportamental textual aplicado somente ao contexto do candidate. O mecanismo não altera código de produção, permissões, ferramentas, avaliadores, modelo, seed, amostra ou protocolo. O candidate recebe a intervenção, mas não recebe scores, respostas, erros ou resultados da fase baseline.

## Gates de validade e promoção

Os resultados são persistidos em `experiments`, `research_runs`, `research_task_results` e `experience_pair_utility`. O envelope registra os identificadores de tarefa, fingerprints de contrato, manifests, modelo, seed, scores, validade de saída, evidência do avaliador e condição de execução.

| Gate | Comportamento implementado |
|---|---|
| Flag | O SDCG exige `life.enabled=true` e `life.feature_flags.sdcg=true`; o default continua desligado. |
| Escopo | A seleção é fixa em três tarefas públicas homogêneas do UGIB Lite. |
| Orçamento | O controlador executa no máximo seis chamadas e possui timeout total configurável limitado a 600 segundos. |
| Paridade | Divergência de modelo, seed, configuração, modo, fingerprint de tarefa, timeout, passos ou allowlist rejeita a execução. |
| Validade | Timeout, erro de execução, saída vazia, score fora de `[0,1]` ou evidência ausente rejeitam a execução. |
| Ganho | Candidate deve superar baseline na média e não pode regredir em nenhuma tarefa pareada. Empate é rejeitado. |
| Autoridade | `OutcomeAuthority` cria um resultado final a partir do verificador registrado; claim do modelo não autoriza promoção. |
| Writeback | `VerifiedWritebackGate` autoriza experiência e skill somente após outcome final bem sucedido. |
| Reuso | A skill somente aparece como validada após três observações candidate, mantendo o limiar existente de uso e taxa de sucesso. |

Em caso de resultado negativo, o experimento permanece persistido como `rejected`, a experiência fica explicitamente não verificada e não há skill reutilizável. As auditorias de writeback negadas continuam disponíveis para inspeção. A promoção positiva utiliza o caminho canônico de experiências, assinaturas, utilidade pareada, firewall de transferência e `SkillService`, sem escrever em um subsistema paralelo.

## Testes executados

A suíte dedicada `tests/test_life_sdcg.py` cobre hipótese única, ausência de escolha humana intermediária, paridade, divergência adversarial de modelo, seed, configuração, timeout, allowlist e output, ausência de ganho, limite de seis execuções, isolamento público e promoção com reuso procedural. Também verifica que o `ContextBuilder` não injeta uma experiência antes de evidência pareada suficiente.

| Verificação | Resultado |
|---|---:|
| Ruff nos arquivos alterados | aprovado |
| Suíte SDCG direcionada | 13 passed |
| Suíte completa | 231 passed, 1 warning |
| Microprobe público determinístico | `promoted`, 6 execuções |
| Benchmark privado ou unseen | não executado |
| Múltiplas seeds | não executadas |
| Inferências longas com Ollama | não executadas |

A suíte completa foi executada com `ULTRON_VECTOR_ENABLED=false` para evitar que uma diferença ambiental do serviço local de embeddings alterasse o teste preexistente de ordenação sem relação com o v0.2. Essa variável não altera o protocolo SDCG nem o código do mecanismo.

## Limitações e interpretação científica

O microprobe não estima a capacidade de um modelo generativo. A fixture determina os resultados baseline e candidate, de modo que o ganho observado é uma verificação de controle e não uma descoberta empírica sobre raciocínio. Também não há múltiplas seeds, comparação estatística confirmatória, amostra inédita, split unseen ou tarefas de transferência. Nenhum resultado deve ser usado para reivindicar generalização ou lift científico.

O candidate e o baseline compartilham o mesmo modo do runner porque o controle experimental relevante é a intervenção comportamental adicional com modelo, seed e orçamento constantes. A separação entre as condições é registrada no envelope do experimento e não depende de uma diferença de modelo ou de permissões. A estratégia ainda é específica ao ciclo e ao domínio público; a transferência para novas classes permanece fora do escopo do v0.2.

> Conclusão operacional: o LIFE v0.2 passou o microprobe bounded de mecanismo. Isso autoriza tratar a implementação como funcional para a etapa atual, mas não autoriza iniciar LIFE v0.3 nem converter o resultado em alegação de autoaperfeiçoamento geral.

## Arquivos relevantes

O protocolo congelado está em [`LIFE_V0_2_PROTOCOL.md`](LIFE_V0_2_PROTOCOL.md). A execução determinística está em [`scripts/run_life_sdcg_probe.py`](scripts/run_life_sdcg_probe.py). A integração reside no controlador existente [`ultron/cognition/life.py`](ultron/cognition/life.py), com reuso de `EmpiricalSelfModel`, `UGIBLiteRunner`, `ExperienceUtilityModel`, `VerifiedWritebackGate`, `ExperienceSignatureBuilder`, `NegativeTransferFirewall` e `SkillService`.

O resultado bruto do microprobe não é parte do código público versionado. Ele foi produzido em diretório temporário isolado e contém apenas a fixture development only, sem contratos privados ou conteúdo do benchmark privado.
