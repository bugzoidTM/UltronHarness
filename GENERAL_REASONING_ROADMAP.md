# HORIZON v0.8 — General Reasoning Core

## Roadmap experimental GR-0 a GR-9

**Status:** proposta para revisão humana. Este arquivo é o único entregável desta etapa.

> **Regra de parada desta etapa:** não implementar GR-1 nem modificar código cognitivo até que este roadmap seja revisado e aprovado. O trabalho só deve avançar quando houver um gate explícito de aprovação humana registrado fora do sistema de benchmark.

## 1. Objetivo e hipótese científica

O objetivo é testar, sem declarar ou tentar implementar AGI, se o mesmo modelo-base pode resolver problemas inéditos em múltiplos domínios com maior generalidade quando recebe uma arquitetura cognitiva incremental. A proposta acrescenta estado epistêmico explícito, hipóteses concorrentes, previsões, atualização de crenças, relações causais, verificações contrafactuais, seleção de operadores e estratégias, backtracking cognitivo e transferência limitada por **verified writeback**.

A hipótese pré-registrada é a seguinte:

> Um sistema que mantém estado epistêmico explícito, gera hipóteses concorrentes, constrói modelos causais, faz previsões, testa as próprias crenças, executa raciocínio contrafactual e seleciona dinamicamente estratégias torna o mesmo modelo-base significativamente mais capaz de resolver problemas novos e transferir conhecimento entre domínios.

O sistema não deve simplesmente “pensar mais”. O resultado de interesse é melhorar a representação do problema, a detecção de desconhecimento, a formulação e eliminação de explicações, a previsão de consequências, a falsificação de premissas, a recuperação após falha, a transferência de princípios e a conclusão externamente verificada.

## 2. Decisão desta auditoria

A auditoria do estado atual indica que o UltronHarness já possui infraestrutura suficiente para iniciar uma sequência experimental pequena, mas ainda não deve receber a arquitetura completa de uma vez. O próximo artefato correto é este roadmap; a alteração de código cognitivo está deliberadamente fora do escopo.

A implementação atual do Horizon já oferece os três modos de controle `full_plan`, `short_horizon` e `next_action`, snapshots e ações persistidos, telemetria de decisões estruturadas, observação obrigatória, invalidação de blocos de curto horizonte, reorientação estruturada, recuperação de false-stop, orientação compartilhada e autoridade externa de outcome [1]. O estado persistido, porém, ainda não separa explicitamente **FACT**, **INFERENCE**, **ASSUMPTION**, **HYPOTHESIS** e **UNKNOWN**, nem mantém o conjunto completo de hipóteses, evidências a favor e contra, previsões, relações causais, checkpoints epistêmicos ou resultados contrafactuais [2].

Há componentes preliminares de comparação contrafactual e recomendação empírica de estratégias, mas eles operam em shadow mode e não constituem ainda um ciclo integrado de raciocínio [3] [4]. A configuração expõe limites gerais de cognição, mas ainda não contém feature flags granulares para os experimentos GR-1 a GR-8 [5]. A infraestrutura de benchmark existente já consegue congelar orientação, verificar modelo, seed, contrato, ferramentas, budget e avaliador privado, além de excluir injeção prévia de experiência; ela deve ser reutilizada sem ampliar a fronteira do evaluator privado [6].

O baseline automatizado observado na auditoria foi de **175 testes aprovados**, com uma advertência de depreciação do `TestClient` e cobertura total de **76,96%**. Esse número é apenas um estado operacional do repositório; não é evidência de ganho de capacidade geral e não deve ser confundido com ATC, GG ou salto científico.

## 3. Invariantes que não podem ser alterados

Os invariantes abaixo são pré-condições de todos os experimentos. Uma violação invalida a medição da variante afetada e bloqueia sua promoção, mesmo que o score observado seja alto.

| Invariante | Contrato operacional | Evidência mínima persistida |
|---|---|---|
| **Shared orientation** | A mesma orientação congelada é criada antes da primeira decisão e compartilhada entre as variantes comparadas. | Hash da missão, seed, allowlist, budget, observações e fixture de referência; correspondência comprovada em cada trace. |
| **Structured decision telemetry** | Toda decisão estruturada registra validade inicial, validade final, reparos, classe de erro, modelo e seed. | Linha append-only em `structured_decisions` e chamada correspondente em `model_calls`. |
| **External OutcomeAuthority** | `stop=true` é somente proposta; sucesso final depende da autoridade externa configurada, sem promoção por alegação do modelo. | Resultado final, nível de autoridade e referências de evidência sanitizadas. |
| **False-stop recovery** | Após `STOP → FAIL`, somente a autoridade externa reabre a cognição com feedback público genérico e uma nova tentativa de avaliação. | Identidade ordinal da tentativa, hash do workspace, verdict e feedback sem segredo privado. |
| **Short-horizon invalidation** | Uma observação que muda as premissas invalida as ações restantes do bloco; não há execução cega da sequência antiga. | Eventos de criação, execução, invalidação, ações descartadas e razão determinística. |
| **Structured reorientation** | Estagnação e action loop exigem estratégia abandonada, estratégia nova materialmente diferente e justificativa. | Snapshot com estratégia ativa, estratégia abandonada, assinatura bloqueada e evento de reorientação. |
| **Verified writeback** | Experiência, skill, memória procedural e princípio transferível só se tornam reutilizáveis após outcome final com autoridade mínima. | Tentativa em `verified_writebacks`, estado de verificação, autoridade e evidência sanitizada. |
| **Safety and boundary** | Nenhum experimento altera permissões, Policy Engine, aprovação, kill switch, evaluator privado, benchmark oculto ou aquisição de credenciais. | Testes de segurança, manifestos de contrato e auditoria de diff. |

Os artefatos cognitivos devem ser estruturados e auditáveis. Não se deve persistir chain-of-thought token a token, nem incluir resposta esperada, fixture secreto, patch ouro ou implementação do evaluator em snapshots, eventos, prompts públicos ou relatórios.

## 4. Princípios metodológicos

Cada experimento ativa **uma capacidade por vez** atrás de uma feature flag. A comparação principal mantém o mesmo modelo-base efetivo, seed, budget de ferramentas, ferramentas autorizadas, contrato de missão, orientação, workspace inicial e evaluator privado. A variante candidata não pode receber conhecimento externo adicional; quando houver memória ou writeback, a origem, o estado de verificação e a autorização devem ser demonstrados.

O runner deve medir o efeito incremental e o custo. Cada trace precisa registrar chamadas LLM, tokens, latência, ações de ferramenta, reparos, observações, decisões, falhas, recuperação e resultado externo. Se a variante ganhar apenas aumentando chamadas, tokens ou tempo, o resultado deve ser reportado como possível efeito de orçamento, não como ganho arquitetural geral. A comparação primária deve usar budget pareado; a análise secundária deve apresentar desempenho por unidade de custo.

Uma execução com qualquer violação metodológica é **measurement invalid**, não uma falha silenciosa nem um PASS. Resultados nulos e negativos são resultados científicos válidos e restringem a hipótese. Nenhuma variante deve ser promovida por inspeção visual de uma resposta ou por alegação do próprio modelo.

O critério de sistema para “salto” somente pode ser avaliado depois de haver: aumento significativo de ATC em missões privadas inéditas; ganho em múltiplos domínios; mesmo modelo-base; persistência em múltiplas seeds; intervalo de confiança de 95% que exclua zero; ganho em famílias não vistas; ausência de leakage; custo de inferência controlado; e ablações identificando os mecanismos causais do efeito.

## 5. Sequência experimental

### GR-0 — Frozen baseline

| Campo | Especificação |
|---|---|
| **INVARIANT** | Fixar o contrato de comparação antes de adicionar qualquer capacidade cognitiva. Preservar orientação compartilhada, autoridade externa, segurança e writeback verificado. |
| **HYPOTHESIS** | O Horizon atual fornece um baseline operacional mensurável, mas não deve ser atribuído a um mecanismo novo. |
| **MINIMUM CODE CHANGE** | Nenhuma mudança cognitiva. Congelar manifesto, versão do benchmark, commit, modelo efetivo, seeds, budget, ferramentas, orientação, fixtures, evaluator e formato dos traces. Se necessário, apenas documentação e harness de execução não cognitivo. |
| **BEHAVIORAL TEST** | Executar `full_plan`, `short_horizon` e `next_action` com o mesmo conjunto de missões e confirmar que cada trace tem orientação, contrato, atribuição de modelo/seed, budget respeitado, outcome externo e status de medição. |
| **ADVERSARIAL TEST** | Injetar mismatch de orientation/fixture, ferramenta fora da allowlist, excesso de budget, fallback como sucesso, tentativa de false-stop e payload contendo segredo do evaluator. Cada caso deve invalidar ou rejeitar a medição sem promover writeback. |
| **ABLATION** | A/B/C do Horizon atual: `full_plan` versus `short_horizon` versus `next_action`, sem estado epistêmico novo e sem injeção de experiência. |
| **SUCCESS GATE** | Pipeline metodologicamente válida, artefato reprodutível, zero violação de invariantes e métricas primárias/auxiliares definidas antes da coleta. Não é necessário haver lift positivo. |
| **STOP CONDITION** | Parar se não for possível demonstrar equivalência de contrato, orientação, seed, modelo e evaluator; nenhum GR posterior pode compensar um baseline inválido. |

O baseline deve ser congelado antes de observar resultados de um candidato. Não se deve ajustar missões, prompts privados, avaliador ou regras de scoring após conhecer o resultado do baseline.

### GR-1 — Epistemic State

| Campo | Especificação |
|---|---|
| **INVARIANT** | O ciclo atual continua sendo a autoridade de execução; o estado epistêmico é uma camada explícita e limitada, não uma nova autoridade nem um novo controller. |
| **HYPOTHESIS** | Separar fatos, inferências, premissas, hipóteses e desconhecidos reduz conclusões indevidas e melhora a recuperação em tarefas novas. |
| **MINIMUM CODE CHANGE** | Adicionar um modelo versionado e validado para `known_facts`, `unknowns`, `assumptions`, `hypotheses`, `hypothesis_confidences`, `contradictions`, `constraints`, `derived_facts`, `open_questions`, `failed_hypotheses`, `active_strategy`, `candidate_strategies`, `evidence_for` e `evidence_against`. Persistir snapshots append-only, com proveniência e confidence baseada em evidência. Adicionar flag desligada por padrão. |
| **BEHAVIORAL TEST** | Dado um caso com uma observação e uma inferência plausível, o sistema mantém tipos distintos, não promove a inferência a fato e inclui uma pergunta aberta quando falta evidência. O snapshot sobrevive a round-trip e resume o estado sem chain-of-thought. |
| **ADVERSARIAL TEST** | Fornecer output do modelo que rotula uma hipótese como fato, contradiz um fato sem evidência, omite unknowns ou contém campos extras/limites inválidos. O schema deve rejeitar ou manter a incerteza; o contrato de ferramenta e a OutcomeAuthority permanecem intactos. |
| **ABLATION** | Baseline GR-0 versus GR-1 com a flag desligada e ligada, usando os mesmos traces, sem hipótese search, causalidade ou contrafactual. |
| **SUCCESS GATE** | Melhora pré-registrada em taxa de classificação epistêmica correta, redução de false-stop ou recuperação, sem regressão de ATC, segurança, SDV, contrato, custo pareado ou writeback. O IC95 do efeito na métrica escolhida deve excluir zero quando o experimento for declarado positivo. |
| **STOP CONDITION** | Parar se o estado for apenas um espelho textual sem alterar uma decisão auditável, se houver promoção silenciosa de hipótese ou se o custo/latência subir sem benefício verificável. |

GR-1 não começa nesta etapa. Ele só pode ser implementado após aprovação deste documento.

### GR-2 — Prediction Before Observation

| Campo | Especificação |
|---|---|
| **INVARIANT** | Toda ação investigativa importante continua sujeita ao contrato da missão, à Policy Engine, à observação e à verificação externa. A previsão não autoriza a ação. |
| **HYPOTHESIS** | Registrar expectativa antes da observação melhora a capacidade de detectar surpresa, atualizar crenças e escolher o próximo teste. |
| **MINIMUM CODE CHANGE** | Adicionar artefato `Prediction` com hipótese, observação esperada, confiança antes, ação/teste, observação obtida, confiança depois e classificação `confirm`, `weaken`, `reject` ou `uncertain`. Persistir o par expected/observed e seu timestamp. |
| **BEHAVIORAL TEST** | Em fixture controlada, gerar expectativa X, observar Y e comprovar atualização distinta para confirmação, enfraquecimento, rejeição e incerteza. A previsão deve aparecer no trace antes da execução da ação e o resultado depois da observação. |
| **ADVERSARIAL TEST** | Tentar registrar a previsão depois da observação, editar uma previsão anterior, usar a observação esperada como observada ou concluir PASS com previsão não testada. O sistema deve rejeitar a ordem inválida e manter append-only. |
| **ABLATION** | GR-1 ligado versus GR-2 desligado/ligado, mantendo estado epistêmico, prompt budget e evaluator constantes. |
| **SUCCESS GATE** | Aumento de prediction accuracy e de assumption falsification rate, com efeito significativo em tarefas inéditas ou melhoria demonstrável de recuperação, sem ATC negativo e sem aumento não controlado de chamadas. |
| **STOP CONDITION** | Parar se previsões forem retrospectivas, cosméticas, impossíveis de auditar ou se a variante passar a favorecer alta confiança sem evidência. |

### GR-3 — Competing Hypotheses

| Campo | Especificação |
|---|---|
| **INVARIANT** | Hipóteses são candidatas; nenhuma hipótese pode ser fato ou conclusão final sem evidência e autoridade adequadas. A seleção de ação continua limitada por contrato e segurança. |
| **HYPOTHESIS** | Manter H1/H2/H3 concorrentes, com evidência a favor e contra, previsões, confiança e informação necessária, melhora a eliminação de explicações erradas. |
| **MINIMUM CODE CHANGE** | Introduzir `HypothesisSet`, `HypothesisUpdate` e `HypothesisElimination`. Limitar quantidade de hipóteses, registrar a razão de atualização e selecionar testes por ganho informacional estimado, sem tree search explosivo. |
| **BEHAVIORAL TEST** | Em problemas com duas explicações compatíveis com a primeira observação, o sistema cria pelo menos duas hipóteses, produz previsões diferentes e elimina a hipótese incompatível após a observação discriminante. |
| **ADVERSARIAL TEST** | Fornecer uma única explicação óbvia, evidência duplicada, evidência contraditória ou confiança máxima sem suporte. O runtime deve manter alternativas ou marcar incerteza, e não inventar evidência. |
| **ABLATION** | GR-2 versus GR-3 com busca concorrente ligada; medir separadamente número de hipóteses, acurácia de eliminação, gain real e custo. |
| **SUCCESS GATE** | Melhoria significativa de `hypothesis_elimination_accuracy`, prediction accuracy ou ATC em famílias inéditas, com cobertura de múltiplos domínios e sem benefício explicado apenas por mais chamadas. |
| **STOP CONDITION** | Parar se as hipóteses forem paráfrases indistinguíveis, se a escolha de teste não usar as previsões ou se a busca aumentar custo sem reduzir incerteza. |

### GR-4 — Assumption Falsification

| Campo | Especificação |
|---|---|
| **INVARIANT** | Premissas continuam explícitas, locais à missão e sujeitas a verificação; falha de uma premissa não pode apagar evidência nem reclassificar silenciosamente o estado. |
| **HYPOTHESIS** | Perguntar qual premissa carrega mais peso e testar o que a falsificaria reduz erros de alta confiança e false-stops. |
| **MINIMUM CODE CHANGE** | Adicionar `AssumptionTest` com premissa, dependências, evidência faltante, condição de falsificação, teste, resultado e impacto em conclusões dependentes. Integrar a seleção do próximo teste sem criar controller novo. |
| **BEHAVIORAL TEST** | Em uma tarefa cuja solução depende de uma precondição não observada, o sistema identifica a precondição, testa-a antes da transformação e atualiza as conclusões quando ela falha. |
| **ADVERSARIAL TEST** | Fazer a precondição parecer verdadeira pelo nome do arquivo, alegação do modelo ou saída stale. O teste deve exigir evidência atual e impedir a conclusão baseada somente na aparência. |
| **ABLATION** | GR-3 com teste de premissa desligado versus ligado; comparar falsification rate, false-stop recovery, ATC e chamadas. |
| **SUCCESS GATE** | Redução significativa de conclusões sustentadas por premissa falsa e/ou aumento de recuperação de false-stop, mantendo writeback bloqueado até outcome final. |
| **STOP CONDITION** | Parar se o módulo apenas formular perguntas sem alterar decisão, se a falsificação puder contornar Policy/OutcomeAuthority ou se produzir rejeições indiscriminadas. |

### GR-5 — Causal State

| Campo | Especificação |
|---|---|
| **INVARIANT** | O modelo causal é mínimo, textual/simbólico, específico da missão e não é um knowledge graph genérico nem fonte independente de autorização. |
| **HYPOTHESIS** | Representar relações `A → B`, `A inhibits B`, `A requires C` e condições `B only if D` melhora a escolha de intervenções e a explicação de observações. |
| **MINIMUM CODE CHANGE** | Criar `CausalState` com nós, relações, confiança, proveniência, contradições e escopo de missão. Expor operações de consulta de variável, dependência e intervenção; registrar atualização após observação. |
| **BEHAVIORAL TEST** | Em fixture com uma precondição e dois efeitos, o sistema responde qual variável explica as observações e escolhe a intervenção que discrimina H1 de H2. |
| **ADVERSARIAL TEST** | Tentar importar relação fora da missão, converter correlação em causalidade sem evidência, criar ciclo não suportado ou usar relação stale após mudança de estado. O estado deve marcar desconhecido/contradição e não autorizar ação fora do contrato. |
| **ABLATION** | GR-4 versus GR-5 com estado causal ligado, sem contrafactual e sem MetaReasoner. |
| **SUCCESS GATE** | Aumento significativo de causal reasoning accuracy ou de ATC em tarefas causais inéditas, com relações relevantes, proveniência completa e custo controlado. |
| **STOP CONDITION** | Parar se o grafo crescer sem limite, se as relações forem apenas uma reformulação da resposta final ou se relações não verificadas influenciarem writeback. |

### GR-6 — Counterfactual Check

| Campo | Especificação |
|---|---|
| **INVARIANT** | A verificação contrafactual é uma operação limitada e auditável; não altera o mundo real, não executa ação fora do contrato e não substitui o evaluator privado. |
| **HYPOTHESIS** | Antes de aceitar conclusão importante, perguntar o que seria esperado se ela fosse falsa revela explicações alternativas e reduz aceitação de conclusões frágeis. |
| **MINIMUM CODE CHANGE** | Adicionar `CounterfactualCheck` com `current_conclusion`, `alternative_world`, `predicted_difference`, `test` e `result`. Executar no máximo uma quantidade configurável por missão e registrar quando o orçamento não permite. |
| **BEHAVIORAL TEST** | Em uma conclusão com alternativa plausível, construir mundo alternativo mínimo, prever diferença, executar teste permitido e atualizar conclusão conforme resultado. |
| **ADVERSARIAL TEST** | Fornecer mundo alternativo idêntico, teste sem diferença prevista, resultado não observado ou conclusão que ignora resultado contrafactual. O schema e o runtime devem marcar incerteza e não fabricar confirmação. |
| **ABLATION** | GR-5 versus GR-6 com contrafactual ligado; medir accuracy, recuperação, tempo, tokens e ações adicionais. |
| **SUCCESS GATE** | Redução significativa de conclusões não falsificadas ou aumento de performance em counterfactual reasoning, em mais de uma família inédita, sem aumento de false-stop nem violação de budget. |
| **STOP CONDITION** | Parar se o check for sempre textual, não gerar teste discriminante ou aumentar custo sem mudar crença ou decisão. |

### GR-7 — Cognitive Backtracking

| Campo | Especificação |
|---|---|
| **INVARIANT** | Backtracking restaura somente um checkpoint epistêmico consistente; não reverte eventos append-only, não apaga auditoria, não altera permissões e não repete uma ação proibida. |
| **HYPOTHESIS** | Após falha observada, identificar a premissa inválida, invalidar conclusões dependentes, restaurar o último estado consistente e escolher outro ramo melhora a recuperação real. |
| **MINIMUM CODE CHANGE** | Persistir `EpistemicCheckpoint` imutável com estado, dependências, evidências, estratégia e assinatura da ação. Implementar rollback lógico de conclusões dependentes e seleção de ramo alternativo, mantendo histórico de falha e autoridade externa. |
| **BEHAVIORAL TEST** | Executar uma missão com H1 inválida, comprovar falha, restaurar checkpoint anterior sem apagar eventos, eliminar H1, escolher H2 e alcançar PASS externo com ação diferente. |
| **ADVERSARIAL TEST** | Tentar fazer rollback apagar evidência, reutilizar writeback falho, repetir a ação gatilho, voltar a uma permissão anterior ou restaurar snapshot com segredo. O teste deve bloquear cada tentativa. |
| **ABLATION** | GR-6 versus GR-7 com backtracking ligado; comparar `backtracking_recovery_rate`, false-stop recovery, ações descartadas e event log. |
| **SUCCESS GATE** | Aumento significativo de backtracking recovery rate e/ou ATC em tarefas de state recovery/debugging, com recuperação comprovada por OutcomeAuthority e sem perda de auditabilidade. |
| **STOP CONDITION** | Parar se rollback for destrutivo, se recuperar apenas por repetir a mesma ação ou se o sucesso ocorrer sem autoridade externa. |

### GR-8 — MetaReasoner

| Campo | Especificação |
|---|---|
| **INVARIANT** | MetaReasoner é um operador de decisão estruturada, não um controller paralelo; a ação final passa pelos mesmos contratos, Policy Engine, observação, verificação e OutcomeAuthority. |
| **HYPOTHESIS** | Escolher explicitamente entre `DECOMPOSE`, `DEDUCT`, `INDUCT`, `ABDUCT`, `COMPARE`, `ELIMINATE`, `SIMULATE`, `COUNTERFACTUAL`, `SEARCH_HYPOTHESES`, `TEST_ASSUMPTION`, `REDUCE_UNCERTAINTY`, `VERIFY_CONSTRAINT` e `BACKTRACK` melhora a estratégia adaptativa. |
| **MINIMUM CODE CHANGE** | Definir schema de `ReasoningOperatorSelection` com operador, razão, incerteza atual, ganho informacional esperado e custo/risk estimados. Limitar operadores elegíveis por estado; persistir a escolha e o resultado. Integrar a política de estratégias A/B/C com expected success, cost, risk, information gain e reversibility. |
| **BEHAVIORAL TEST** | Em tarefas com estados diferentes, o sistema escolhe operadores diferentes, explica a escolha de forma estruturada e muda de operador após evidência que reduz o valor do operador anterior. |
| **ADVERSARIAL TEST** | Tentar escolher operador inexistente, executar operador sem pré-condição, selecionar sempre a estratégia óbvia, declarar ganho informacional sem teste ou usar MetaReasoner para contornar budget. O runtime deve rejeitar ou limitar. |
| **ABLATION** | GR-7 versus GR-8 com MetaReasoner ligado; incluir comparação com seleção aleatória/estática pré-registrada somente como controle, sem promover aleatoriedade a produto. |
| **SUCCESS GATE** | ATC e Generalization Gain positivos e significativos em múltiplos domínios/famílias, com ablações que identifiquem contribuição incremental de pelo menos um mecanismo e sem regressão de segurança, writeback, SDV ou custo pareado. |
| **STOP CONDITION** | Parar se a escolha de operador não for auditável, se o MetaReasoner virar um segundo controller, se todas as tarefas usarem o mesmo operador ou se o ganho desaparecer sob budget pareado. |

### GR-9 — Cross-Domain Generalization Benchmark

| Campo | Especificação |
|---|---|
| **INVARIANT** | O benchmark novo é privado, congelado, inédito e isolado; nenhuma missão, fixture, contrato oculto, resposta esperada, patch ouro ou implementação do evaluator entra no corpus de experiência ou nos prompts públicos. |
| **HYPOTHESIS** | Princípios abstratos derivados de experiências verificadas transferem melhor para famílias não vistas do que respostas, procedimentos literais ou memória episódica não abstraída. |
| **MINIMUM CODE CHANGE** | Criar o benchmark privado `General Reasoning v1` com evaluator baseado no estado final real e splits explícitos de treino/ablação, validação e famílias não vistas. Adicionar apenas a telemetria e o runner necessários para calcular GG, transfer gain, calibração e custo; manter o evaluator fora da árvore pública. |
| **BEHAVIORAL TEST** | Executar fresh baseline e experienced variant com o mesmo modelo, seed, budget, ferramentas, orientação e contrato. Verificar que somente writebacks verificados e princípios permitidos atravessam o gate e que o desempenho é medido por estado final real. |
| **ADVERSARIAL TEST** | Tentar inserir template literal do benchmark, consultar evaluator privado, vazar resposta no prompt, reutilizar fixture, misturar família vista no split unseen ou promover experiência FAIL. A pipeline deve detectar leakage e invalidar a execução. |
| **ABLATION** | Comparar A: Horizon atual; B: + Epistemic State; C: + Hypothesis Search; D: + Causal/Counterfactual; E: + MetaReasoner; e F: + transferência somente por verified writeback. Cada etapa deve ser executada com flag única e, quando aplicável, com todas as demais desligadas. |
| **SUCCESS GATE** | Somente declarar Generalization Gain se ATC subir significativamente em tarefas privadas inéditas, houver ganho em múltiplos domínios e seeds, IC95 excluir zero, o efeito sobreviver em famílias unseen, não houver leakage, custo não explicar sozinho a melhora e as ablações atribuírem o efeito a mecanismos identificáveis. |
| **STOP CONDITION** | Parar e classificar como inconclusivo se qualquer requisito de validade falhar. Um resultado positivo em famílias vistas, uma resposta que parece boa, um único seed ou um ganho explicável por mais inference não autoriza chamar o resultado de salto. |

## 6. Benchmark e métricas pré-registradas

O benchmark final deve conter problemas inéditos de **causal reasoning, constraint satisfaction, debugging, planning, scientific inference, logical deduction, abductive reasoning, counterfactual reasoning, state recovery** e **novel rule induction**. Os templates não podem ser repetidos literalmente entre splits. Cada missão deve possuir evaluator privado baseado no estado final real, não em qualidade textual.

| Métrica | Definição operacional | Uso |
|---|---|---|
| **ATC** | Fração de missões com sucesso externo atribuível a decisão estruturada do modelo, não a fallback. | Primária. |
| **First-pass success** | PASS externo na primeira proposta de conclusão, sem false-stop recovery. | Eficiência de primeira tentativa. |
| **False-stop recovery** | Falha externa seguida de feedback público, ação/estratégia diferente e PASS autoritativo. | Robustez do loop. |
| **Hypothesis elimination accuracy** | Proporção de hipóteses incompatíveis corretamente eliminadas após evidência discriminante. | GR-3. |
| **Prediction accuracy** | Concordância auditável entre observação esperada e observação classificada após o teste. | GR-2. |
| **Assumption falsification rate** | Proporção de premissas falsas relevantes que são identificadas e testadas antes da conclusão. | GR-4. |
| **Backtracking recovery rate** | Proporção de falhas com restauração consistente e recuperação autoritativa. | GR-7. |
| **Calibration error** | Erro entre confidence e outcome observado, com penalização de alta confiança em resultado errado. | Todas as variantes. |
| **Cross-domain transfer gain** | Diferença de desempenho entre tarefa-alvo com princípio verificado e baseline sem ele, em domínio permitido. | GR-9. |
| **Generalization Gain** | `performance on unseen families with architecture − performance on unseen families with same base model baseline`. | Critério final. |
| **Tool/LLM efficiency** | Ferramentas, chamadas, tokens, latência e custo por missão, sempre pareados com o baseline. | Controle de confounds. |
| **SDV** | Decisões estruturadas válidas ao final ÷ decisões estruturadas. | Qualidade do contrato de decisão. |

A análise deve usar pares missão-seed e reportar intervalo de confiança de 95% para o efeito, além de score bruto, total de casos, seeds, famílias, custo e validade. A política estatística detalhada, incluindo unidade de reamostragem e correção para múltiplas comparações, deve ser congelada antes de consultar resultados do benchmark final.

## 7. Política de flags, ablação e promoção

As flags devem ser independentes, explícitas e desligadas por padrão até aprovação do experimento correspondente. O estado da configuração precisa aparecer no manifesto e no trace; não é suficiente inferi-lo a partir do prompt.

| Flag proposta | Default nesta etapa | Ativação permitida |
|---|---:|---|
| `cognition.epistemic_state` | `false` | Após aprovação do roadmap e conclusão válida de GR-0. |
| `cognition.prediction_before_observation` | `false` | Somente após gate GR-1. |
| `cognition.competing_hypotheses` | `false` | Somente após gate GR-2. |
| `cognition.assumption_falsification` | `false` | Somente após gate GR-3. |
| `cognition.causal_state` | `false` | Somente após gate GR-4. |
| `cognition.counterfactual_check` | `false` | Somente após gate GR-5. |
| `cognition.cognitive_backtracking` | `false` | Somente após gate GR-6. |
| `cognition.meta_reasoner` | `false` | Somente após gate GR-7. |
| `research.general_reasoning_benchmark_v1` | `false` | Somente após pipeline privada, congelada e auditada. |

Uma feature não pode ser promovida por ter passado somente no teste unitário. A promoção exige teste comportamental, teste adversarial, ablação isolada, medição válida, ausência de regressão de segurança e aprovação humana. Se uma feature falhar, ela permanece desligada enquanto a hipótese e o diagnóstico são registrados; não se adiciona outro controller para mascarar o resultado.

O self-improvement é limitado a: falha observada; hipótese sobre a fraqueza; política candidata; experimento isolado; benchmark; ablação; aprovação humana; promoção. O sistema não pode alterar permissões, segurança, credenciais, evaluator, benchmark oculto, deployment ou configuração de cobrança.

## 8. Checklist de revisão humana antes de GR-1

| Pergunta de revisão | Critério de aprovação |
|---|---|
| O escopo está limitado ao roadmap nesta etapa? | Sim; nenhum código cognitivo foi modificado. |
| Os invariantes Horizon atuais estão nomeados e testáveis? | Sim; cada um tem contrato e evidência. |
| A sequência adiciona uma capacidade por vez? | Sim; cada GR possui flag e ablação individual. |
| A hipótese de ganho é distinguida de aumento de inference? | Sim; budget pareado e métricas de custo estão definidos. |
| O evaluator privado e a fronteira do benchmark permanecem isolados? | Sim; leakage invalida a medição. |
| Há stop conditions explícitas? | Sim; cada GR possui condição de parada. |
| O benchmark mede estado final real e generalização unseen? | Planejado em GR-9; não implementado nesta etapa. |
| Há aprovação humana registrada? | Deve ser obtida antes de ativar `cognition.epistemic_state`. |

## 9. Estado de parada

A auditoria e a escrita do roadmap estão concluídas. O próximo passo correto é revisão e aprovação humana deste arquivo. Até essa aprovação, o produto deve permanecer no estado atual, com as flags novas inexistentes ou desligadas, sem implementação de GR-1 e sem qualquer alteração no código cognitivo, segurança, permissões, evaluator privado ou fronteira do benchmark.

## Referências

[1]: `ultron/core/receding_controller.py` — controller Horizon, snapshots, observação, invalidação, reorientação e telemetria.
[2]: `ultron/schemas.py` e `ultron/db.py` — schemas atuais e tabelas persistidas do estado cognitivo.
[3]: `ultron/cognition/counterfactual.py` — deliberador contrafactual preliminar em shadow mode.
[4]: `ultron/cognition/strategy_policy.py` — política empírica de estratégia em shadow mode.
[5]: `config/default.yaml` — limites atuais e ausência de flags granulares para GR-1 a GR-8.
[6]: `ultron/research/horizon_control.py` e `HORIZON_V0_7_REPORT.md` — benchmark Horizon, orientação compartilhada, OutcomeAuthority, false-stop recovery, invalidação e verified writeback.
[7]: `tests/test_horizon_foundations.py` e demais `tests/test_horizon_*.py` — contratos comportamentais e adversariais já aprovados.
