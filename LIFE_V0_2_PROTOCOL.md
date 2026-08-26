# LIFE v0.2 — Self Directed Capability Gain

## 1. Objetivo e escopo

O único objetivo deste ciclo é verificar se o LIFE consegue transformar uma lacuna de competência empiricamente observada em uma hipótese comportamental única, comparar uma condição baseline com uma condição candidate pareada e promover a hipótese somente quando o ganho for confirmado por um avaliador público registrado.

Este protocolo é um mecanismo de engenharia limitado. Ele não mede AGI, vontade forte, consciência, generalização ampla, transferência ou autoaperfeiçoamento geral.

> Invariante: `COMPETENCE_GAP → investigação escolhida pelo LIFE → uma hipótese → baseline → intervenção comportamental limitada → candidate → gate → writeback verificado somente se houver ganho`.

## 2. Condição de entrada

A execução exige `life.enabled=true`, `life.feature_flags.tension_detection=true`, `life.feature_flags.goal_selection=true` e a flag independente `life.feature_flags.sdcg=true`. A entrada deve conter pelo menos uma estimativa persistida em `capability_estimates` com `sample_size >= competence_min_sample` e `success_rate <= competence_max_success_rate`.

Se houver mais de uma lacuna, o LIFE escolhe deterministicamente uma única tensão pela ordem já auditada de importância, confiança e identificador. Somente essa tensão é persistida e investigada nesta execução.

## 3. Hipótese e intervenção

A hipótese não é fornecida por uma pessoa e não é escolhida depois de observar resultados. O LIFE deriva exatamente uma hipótese de um tipo de lacuna e registra `selection_source=life_gap_policy`.

Para a lacuna pública de representação, a intervenção congelada é uma instrução comportamental curta: representar explicitamente o estado inicial, a transformação ou restrição principal e o estado desejado antes de responder; então verificar a consistência da resposta e respeitar o formato solicitado.

A intervenção é aplicada apenas ao contexto textual da condição candidate. Ela não altera código de produção, permissões, avaliador, modelo, amostra, ferramentas ou política. O candidate não recebe saídas, scores ou erros da fase baseline.

## 4. Amostra pública e orçamento

A amostra congelada é `reasoning_06`, `reasoning_07` e `reasoning_08` do UGIB Lite público. São três microtarefas homogêneas de raciocínio, com avaliadores públicos registrados no harness e contratos públicos de trinta segundos e um passo máximo.

Cada tarefa é executada uma vez em baseline e uma vez em candidate, totalizando no máximo seis chamadas. A seed congelada é `42`. O modelo é um único identificador explícito resolvido antes da primeira chamada e deve permanecer igual nas seis chamadas. O modo de execução é o mesmo nas duas condições, a lista de ferramentas permitidas é a mesma e o fingerprint do contrato da tarefa deve ser idêntico. O prazo total padrão é de 540 segundos e nunca pode ultrapassar 600 segundos.

Os resultados de cada chamada são persistidos pelo runner público em `research_runs` e `research_task_results`. O envelope do experimento é persistido em `experiments`; os deltas válidos são persistidos em `experience_pair_utility`.

## 5. Gates de validade

A execução é rejeitada sem writeback quando a amostra pública não existe, quando o benchmark ou sua versão divergem, quando o modelo efetivo diverge, quando a seed diverge, quando o fingerprint de tarefa, timeout, passos ou allowlist diverge, quando há timeout ou erro de execução, quando a saída é vazia ou quando a evidência do avaliador é insuficiente.

A pontuação é a média dos três scores persistidos. Para promoção, `candidate_score` deve ser estritamente maior que `baseline_score` e nenhum candidate pode regredir em relação à tarefa pareada correspondente. Empate ou piora é resultado negativo e permanece persistido como `rejected`.

O resultado final é convertido por `OutcomeAuthority` a partir do avaliador público registrado. Claims do modelo, status textual de task e pontuação isolada sem contrato não autorizam writeback.

## 6. Promoção e reuso

Depois de todos os gates, o `VerifiedWritebackGate` é avaliado para a experiência e para a skill da estratégia. Somente uma decisão autorizada permite marcar a experiência como verificada e registrar a skill verificada. A skill recebe três observações correspondentes às três tarefas candidates e só aparece em `reusable_procedures()` quando o limiar existente de três usos e taxa de sucesso é satisfeito.

Sem ganho, sem evidência suficiente ou com qualquer divergência de contrato, nenhuma skill é criada e nenhuma experiência é marcada como verificada. Auditorias negadas continuam registradas.

## 7. Interpretação congelada

Um resultado positivo neste microprobe seria evidência de que o mecanismo bounded de seleção, intervenção, verificação e writeback funciona sob as condições públicas especificadas. Ele não sustenta afirmações sobre generalização, transferência para tarefas novas, desempenho privado ou desenvolvimento cognitivo aberto. Um resultado negativo exige corrigir somente este mecanismo antes de qualquer etapa posterior.

## 8. Proibições

Este protocolo não usa o benchmark privado de raciocínio geral, split unseen, múltiplas seeds, otimização baseada nos próprios resultados, autoedição de código, novos subsistemas cognitivos, multiagentes, permissões novas, alteração de avaliador ou alteração silenciosa de modelo e amostra.
