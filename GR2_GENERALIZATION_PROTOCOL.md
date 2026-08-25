# Protocolo pré-registrado de generalização do GR-2

## 1. Finalidade e estado do protocolo

Este documento define o protocolo de avaliação confirmatória do GR-2 — *Prediction Before Observation*. O protocolo deve ser congelado **antes** da abertura dos resultados privados confirmatórios. Ajustes posteriores à inspeção das métricas devem ser registrados como emenda, com justificativa, data, escopo e impacto esperado.

O objetivo não é demonstrar uma forma geral de inteligência. O objetivo é testar uma hipótese incremental e limitada: se registrar previsões antes de observações melhora a resolução externa de tarefas inéditas quando o mesmo modelo-base recebe uma arquitetura de controle com Prediction Before Observation.

O protocolo é composto por duas etapas. A primeira é uma auditoria de prontidão e calibração, que pode usar missões públicas ou privadas já conhecidas sem produzir uma conclusão confirmatória. A segunda é a avaliação confirmatória em famílias privadas inéditas, com evaluator isolado e splits congelados.

> Nenhuma métrica observada na etapa de calibração pode ser usada para selecionar tarefas, seeds, famílias, thresholds, prompts, orçamento ou método estatístico da etapa confirmatória.

## 2. Pergunta científica

A pergunta principal é:

> Em pares missão-seed idênticos e sob o mesmo modelo-base efetivo, a variante GR-2 com `prediction_before_observation=true` apresenta maior taxa de conclusão externa autoritativa do que a variante GR-1 com `prediction_before_observation=false`, em famílias privadas inéditas e sem leakage?

A unidade experimental é o par `(missão, seed)`. Cada par é executado em duas variantes, GR-1 e GR-2, com a mesma orientação congelada, contrato, ferramentas, budget, workspace inicial e evaluator. As cópias de workspace devem ser independentes para impedir que a primeira variante altere o estado inicial da segunda.

A unidade de inferência é a **família de tarefa**, não a chamada LLM, o passo, o tool call ou a missão isolada. Missões da mesma família podem compartilhar estrutura, template ou dificuldade; tratá-las como independentes produziria intervalos excessivamente otimistas. A análise principal deve agrupar a reamostragem por família.

## 3. Hipóteses e estimando

### 3.1 Hipótese primária

`H0`: a diferença média de ATC entre GR-2 e GR-1 em famílias unseen é zero ou não supera o limiar mínimo de interesse.

`H1`: GR-2 apresenta diferença positiva de ATC em famílias unseen, mantendo o mesmo modelo-base e custo pareado.

Para cada par `i`, define-se `Y_GR1,i` e `Y_GR2,i` como indicadores binários de PASS externo final. O efeito pareado é:

`D_i = Y_GR2,i − Y_GR1,i`.

O estimando primário é:

`Δ_ATC = E_family[D_i]`.

O limiar mínimo de interesse será **5 pontos percentuais de ATC**, salvo emenda aprovada antes da abertura dos resultados confirmatórios. Um efeito estatisticamente diferente de zero, mas menor que esse limiar, será classificado como estatisticamente detectado e praticamente pequeno.

### 3.2 Hipóteses secundárias

A variante GR-2 poderá apresentar redução de false-stops, aumento de first-pass success, aumento de prediction accuracy independente, aumento de assumption falsification rate e melhoria de eficiência por custo. Essas hipóteses são secundárias e não autorizam, isoladamente, uma declaração de generalização geral.

Também será testada uma hipótese de não regressão de segurança: a ativação do GR-2 não deve aumentar violações de contrato, chamadas fora da allowlist, excesso de budget, pre-decision tool calls, writeback não verificado, leakage ou falhas de autoridade externa.

## 4. Benchmark privado General Reasoning v1

### 4.1 Estrutura mínima requerida

A avaliação confirmatória não deve reutilizar diretamente os artefatos públicos `forge_e2e_v1`, `transfer100_v3` ou `transfer100_v4` como benchmark final de generalização. Esses ativos são úteis para testes de pipeline e calibração, mas não devem ser tratados como famílias privadas inéditas se seus templates, scripts, fixtures ou contratos já orientaram o desenvolvimento.

A pasta privada deve possuir, no mínimo, a seguinte estrutura lógica:

```text
UltronHarness_private/
└── general_reasoning_v1/
    ├── contracts.json
    ├── evaluator.py
    ├── split_manifest.json
    ├── leakage_policy.json
    ├── calibration/
    │   ├── task_ids.json
    │   └── evaluator_inputs.json
    ├── validation/
    │   ├── task_ids.json
    │   └── evaluator_inputs.json
    └── unseen/
        ├── task_ids.json
        └── evaluator_inputs.json
```

O diretório privado atualmente disponível contém `forge_e2e_v1`, `forge_router_v1`, `transfer100_v3` e `transfer100_v4`, mas não contém ainda um diretório `general_reasoning_v1` identificado com os contratos confirmatórios necessários. Portanto, a **prontidão de execução confirmatória está bloqueada** até que o benchmark privado seja entregue e auditado.

### 4.2 Famílias de tarefa

O benchmark deve cobrir pelo menos dez famílias, com duas famílias de reserva para substituir qualquer família que falhe nos testes de leakage ou não alcance o tamanho planejado:

| Família | Exemplo de capacidade | Condição de sucesso | Risco de leakage a controlar |
|---|---|---|---|
| Causal reasoning | distinguir causa, correlação e intervenção | estado final compatível com intervenção causal | relações literais memorizadas |
| Constraint satisfaction | satisfazer restrições conflitantes | artefato final passa todas as restrições | solução/solver embutido |
| Debugging | localizar e reparar falha | testes privados passam após alteração | patches ou mensagens de erro repetidas |
| Planning | executar sequência dependente de estado | estado final e invariantes corretos | plano textual fixo |
| Scientific inference | inferir regra a partir de observações | previsão/teste final confirmado | exemplos com resposta explícita |
| Logical deduction | derivar consequência necessária | conclusão e evidência formal corretas | templates de prova repetidos |
| Abductive reasoning | selecionar explicação compatível | explicação discrimina alternativas | prior de hipótese vazado |
| Counterfactual reasoning | avaliar mundo alternativo | diferença prevista e estado final corretos | evaluator acessível |
| State recovery | recuperar após estado inconsistente | restauração sem repetir ação inválida | snapshot ou patch ouro |
| Novel rule induction | induzir regra não literal | regra aplicada a instâncias novas | regra presente em corpus público |
| Família reserva A | tarefa composta não vista | evaluator privado | exposição durante calibração |
| Família reserva B | tarefa de domínio diferente | evaluator privado | sobreposição semântica excessiva |

Cada família deve conter pelo menos vinte missões confirmatórias semanticamente distintas. A similaridade deve ser auditada por identificadores de template, hashes de estrutura e revisão cega de sobreposição. Missões que variem apenas nomes, números ou caminhos não contam como casos independentes de generalização.

### 4.3 Splits

O benchmark deve separar claramente:

| Split | Uso | Pode influenciar o protocolo confirmatório? |
|---|---|---:|
| Calibration | testar instalação, schema, evaluator e smoke | Não, após congelamento |
| Validation | verificar erro de execução e corrigir problemas antes do freeze | Não, depois do freeze |
| Unseen | testar generalização primária | Sim, somente na análise final |

As famílias unseen não podem aparecer na calibração, no ajuste de prompts, na seleção de thresholds, no desenvolvimento de regras de classificação ou em exemplos de memória. Se uma família unseen for aberta para depuração, ela deixa de ser unseen e deve ser movida para validation.

## 5. Variantes e ablações

### 5.1 Comparação primária

A comparação confirmatória principal será:

| Variante | Estado epistêmico | Prediction Before Observation | Outros mecanismos |
|---|---:|---:|---|
| GR-1 control | Ligado conforme baseline aprovado | Desligado | GR-3 a GR-9 desligados |
| GR-2 candidate | Ligado conforme baseline aprovado | Ligado | GR-3 a GR-9 desligados |

A flag GR-2 deve aparecer no manifesto, no artefato do benchmark e em cada trace. Não será permitido inferir a ativação apenas observando prompts ou eventos.

### 5.2 Controles secundários

Se houver orçamento, serão executados três controles adicionais:

| Controle | Finalidade |
|---|---|
| GR-0 frozen | medir o custo de manter o estado epistêmico desligado, quando o baseline histórico for compatível |
| Static expectation control | registrar uma expectativa não adaptativa de custo equivalente, sem atualizar belief após observação |
| Shuffled prediction control | embaralhar expectativas dentro da família, somente como controle negativo e sem promoção de aleatoriedade |

O controle estático não deve ser chamado de variante cognitiva. Ele serve para separar o efeito de mais telemetria ou tokens do efeito temporal de previsão e atualização. O controle embaralhado só será executado se houver uma definição segura que não aumente leakage nem introduza um segundo controller.

### 5.3 Condições pareadas

Para cada missão e seed, as variantes devem receber:

- a mesma orientação congelada e o mesmo `orientation_hash`;
- o mesmo modelo efetivo e alias registrado;
- o mesmo seed de geração;
- a mesma allowlist de ferramentas;
- o mesmo intervalo de budget;
- o mesmo workspace inicial, clonado antes da primeira execução;
- o mesmo contrato de outcome externo;
- o mesmo evaluator privado, chamado somente após a execução;
- o mesmo limite de chamadas e tokens, quando a análise for de budget pareado.

O candidato não pode receber experiências, memórias, respostas, fixtures ou procedimentos verificados que o controle não receba. Se o estudo quiser testar transferência, deverá abrir uma etapa separada com verified writeback e uma ablação própria.

## 6. Seeds, tamanho e poder

### 6.1 Plano de execução

O plano recomendado é de **12 famílias**, sendo dez famílias primárias e duas reservas, **20 missões por família** e **quatro seeds**. Isso produz:

`12 × 20 × 4 = 960` pares missão-seed planejados.

A análise confirmatória primária usará somente as dez famílias primárias que passarem no gate de leakage e completude, totalizando até 800 pares. As famílias de reserva substituem uma família somente se a substituição ocorrer antes da abertura dos resultados unseen e for registrada no manifesto.

Se o custo tornar quatro seeds inviável, o protocolo mínimo operacional será de três seeds e 720 pares com doze famílias, mas esse cenário deverá ser rotulado como versão reduzida e terá menor poder. Um único seed não é admissível para a declaração confirmatória de generalização.

### 6.2 Unidade de poder

A análise de poder deve ser feita sobre o efeito pareado por família, não sobre o número bruto de chamadas. Antes da coleta, devem ser congelados o efeito mínimo de interesse, o nível alfa, o número de famílias, o número de missões por família, a quantidade de seeds e a correlação esperada entre variantes.

Como o outcome é binário e pareado, a tabela de pares discordantes será reportada. Uma aproximação inicial pode usar McNemar ou simulações de poder baseadas em taxas de discordância esperadas. A decisão final sobre o método de intervalo e teste deve ser escrita antes da execução confirmatória. A análise de poder será tratada como planejamento, não como evidência posterior.

Se o piloto de calibration revelar uma taxa de PASS tão baixa que o efeito mínimo de interesse seja impossível de detectar com o número planejado de casos, a execução deve parar para revisão de instrumento. Não será permitido aumentar a amostra depois de observar o resultado unseen apenas porque o valor de `p` ficou próximo do limiar.

## 7. Ground truth e evaluator

### 7.1 Estado final real

O evaluator privado deve verificar o estado final real do workspace, não a qualidade textual da resposta. Cada missão deve possuir um contrato mínimo de outcome:

```text
success = evaluator(private_contract, final_workspace_state, sanitized_trace_metadata)
```

O evaluator não deve receber a resposta esperada como campo público do prompt. O resultado público ao runtime deve ser limitado a `PASS` ou `FAIL`, feedback genérico e referências sanitizadas. Detalhes do erro privado permanecem no evaluator e no artefato privado de análise.

### 7.2 Rótulo independente para previsão

Para medir prediction accuracy de forma não circular, o evaluator deve produzir uma variável de outcome independente da classificação interna do serviço de previsão. O trace deve preservar:

- expectativa registrada antes da ação;
- observação real após a ação;
- status bruto da ferramenta;
- verificação interna;
- resultado privado final;
- classificação de previsão;
- confidence antes e depois;
- referência da evidência;
- timestamp e ordem temporal.

A classe de acerto da previsão deve ser calculada no pós-processamento privado comparando a expectativa com o outcome real. O verificador usado para permitir avanço no controller não deve ser a única fonte da métrica científica.

## 8. Política contra leakage

A avaliação deve possuir um `leakage_policy.json` congelado, com regras para conteúdo proibido, hashing, origem de dados e tratamento de incidentes. São considerados leakage:

- incluir respostas, patches ouro, fixtures privados, contratos ocultos ou implementação do evaluator em prompts, snapshots, eventos ou memórias;
- consultar diretamente o evaluator ou seus arquivos durante a execução da missão;
- usar uma família unseen em calibração ou depuração;
- copiar templates literais entre calibration, validation e unseen;
- inserir no contexto de uma variante artefatos produzidos pela outra variante;
- promover experiência derivada de FAIL ou outcome não autoritativo;
- ajustar prompts, thresholds ou scoring após consultar qualquer trace unseen;
- inferir labels privados de mensagens de erro, nomes de arquivos ou hashes.

Cada execução deve produzir um `leakage_audit` com resultado binário, regras verificadas, hashes de corpus e origem de cada contexto injetado. Qualquer violação transforma a execução afetada em `measurement_invalid` e bloqueia a promoção, mesmo que o score seja alto.

## 9. Protocolo operacional

### Fase A — Freeze

Antes da coleta, devem ser congelados commit, versão do benchmark, manifest de famílias, IDs das missões, contratos, modelo efetivo, seeds, budget, allowlist, flags, versão do prompt, versão do evaluator, política de leakage e método estatístico. O hash desse manifesto deve aparecer em todos os traces.

### Fase B — Calibration

Executar um pequeno subconjunto de calibration somente para verificar instalação, criação de tarefa, orientação, execução, evaluator, persistência e exportação do trace. Nenhuma decisão de desenho confirmatório pode usar o score dessa fase.

### Fase C — Validation

Executar validation com os mesmos contratos, mas sem abrir unseen. O objetivo é verificar que o sistema não deixa previsões pendentes, não gera chamadas fora da allowlist, não extrapola budget e não falha ao clonar workspaces. Correções permitidas nesta fase devem produzir novo commit e novo freeze.

### Fase D — Confirmatory unseen

Para cada família, missão e seed:

1. criar a orientação compartilhada;
2. congelar o fixture e seus hashes;
3. clonar o workspace para GR-1 e GR-2;
4. executar a ordem de variantes definida por seed, sem misturar dados entre cópias;
5. persistir previsões antes da ação na variante GR-2;
6. executar a ação apenas através do contrato, Policy Engine e aprovação existentes;
7. persistir a observação somente após execução e verificação;
8. chamar o evaluator privado após o estado final;
9. persistir PASS/FAIL, autoridade, referências sanitizadas e hash do workspace;
10. exportar trace completo sem conteúdo privado proibido;
11. validar o trace antes de incluir o par na análise.

### Fase E — Lock e análise

Depois de concluída a coleta, o diretório unseen deve ser tratado como somente leitura. O relatório deve ser gerado por um script de análise versionado, usando apenas o manifesto e os artefatos exportados. Qualquer trace inválido deve permanecer na contagem de auditoria e ser excluído da estimativa somente conforme regra pré-especificada.

## 10. Validade do trace

Um trace só é elegível para a análise primária se cumprir todos os itens:

| Item | Critério |
|---|---|
| Modelo | todas as chamadas usam o modelo efetivo registrado |
| Seed | todas as chamadas usam o seed do par |
| Orientação | hash idêntico entre GR-1 e GR-2 |
| Contract | allowlist, budget e `requires_external_outcome` coincidem |
| Segurança | nenhuma ferramenta fora da allowlist e nenhuma permissão alterada |
| Temporalidade | previsão registrada antes da ação; outcome depois da observação |
| Completeness | toda previsão terminal tem observação ou é marcada pending por aprovação/cancelamento |
| Evaluator | sem erro e com autoridade privada correta |
| Leakage | auditoria privada sem violação |
| Writeback | somente experiência verificada pode atravessar o gate |

Uma falha em uma condição invalida o par para a análise confirmatória. O número de pares inválidos e o motivo devem ser reportados; não se deve simplesmente removê-los sem contagem.

## 11. Análise estatística congelada

### 11.1 Primária

Calcular `D_i` em cada par válido. Reportar média, mediana, proporção de pares `GR-2=1, GR-1=0`, proporção `GR-2=0, GR-1=1`, intervalo de confiança de 95% agrupado por família e teste pareado bilateral com alfa de 0,05.

A reamostragem deve selecionar famílias inteiras, mantendo todas as missões e seeds daquela família dentro de cada réplica. O número de réplicas bootstrap será fixado, por exemplo 10.000, antes do freeze. A semente do bootstrap será registrada no manifest de análise e não será usada para criar dados de execução.

### 11.2 Secundárias

Para first-pass success, false-stop recovery, prediction accuracy independente e assumption falsification rate, reportar diferenças pareadas, intervalos de confiança agrupados e contagens brutas. Para confidence, reportar Brier score e erro de calibração por bins previamente fixados. Para custo, reportar chamadas, tokens, latência, tool calls e custo por missão, além de eficiência por PASS.

### 11.3 Múltiplas comparações

Somente ATC unseen é confirmatória. Métricas secundárias serão exploratórias ou usarão correção Benjamini–Hochberg com família de hipóteses definida no manifest. Não será permitido escolher como principal a métrica com maior efeito pós-coleta.

## 12. Regras de parada e decisão

### Parar antes da coleta unseen

A execução deve parar se o evaluator privado estiver ausente, se o manifest não congelar os splits, se o workspace não puder ser clonado, se a orientação compartilhada não for reproduzível, se o modelo efetivo não puder ser atribuído ou se a política de leakage não puder ser verificada.

### Invalidar a medição

A medição deve ser marcada inválida se houver pre-decision tool call, mismatch de orientação, mismatch de fixture, chamada fora da allowlist, budget excedido, evaluator error, leakage, previsão retrospectiva, observação duplicada, writeback não verificado ou trace incompleto sem regra de tratamento prévia.

### Declarar resultado nulo

O resultado é nulo se o intervalo de confiança incluir zero ou se o efeito não superar o limiar mínimo de interesse. Um resultado nulo é informativo e não autoriza ativar GR-3.

### Declarar efeito positivo limitado

Somente será permitido declarar um efeito positivo limitado se ATC unseen superar zero e o limiar de 5 pontos percentuais, o IC95 excluir zero, pelo menos oito das dez famílias primárias estiverem válidas, não houver regressão de segurança e o efeito não desaparecer quando custo e quantidade de chamadas forem pareados.

### Bloquear promoção

A promoção deve ser bloqueada se o ganho surgir somente em famílias vistas, apenas em um seed, somente no modelo fallback, somente com mais chamadas, somente após ajuste de prompts, ou se a prediction accuracy independente não puder ser calculada.

## 13. Artefatos esperados

A execução confirmatória deve produzir:

```text
artifacts/research/general_reasoning_v1/<run_id>/
├── manifest.json
├── protocol_hash.txt
├── summary.json
├── paired_results.jsonl
├── family_summary.json
├── metrics.json
├── confidence_intervals.json
├── leakage_audit.json
├── invalid_traces.jsonl
├── cost_analysis.json
└── trace_index.jsonl
```

`paired_results.jsonl` deve conter apenas campos sanitizados. O conteúdo privado do evaluator, respostas esperadas e fixtures não devem ser exportados para esse arquivo. `invalid_traces.jsonl` deve conter IDs, hashes, motivo da invalidação e metadados suficientes para auditoria, sem segredo.

## 14. Critério de prontidão

| Gate | Estado atual | Próxima ação |
|---|---|---|
| GR-2 implementado | Passou | Mantido atrás de flag |
| Piloto pareado | Passou como instrumentação | Não usar como confirmação |
| Modelo-base confirmatório | Pendente | Fixar `qwen2.5:0.5b` via alias `ollama`, salvo emenda |
| General Reasoning v1 privado | Bloqueado | Entregar `contracts.json`, evaluator e splits |
| Leakage policy | Pendente | Congelar política e hashes |
| Power analysis | Pendente | Fixar efeito mínimo, famílias e seeds |
| Runner confirmatório | Parcial | Implementar após ativos privados |
| Aprovação humana do protocolo | Pendente | Revisar este documento antes da coleta |

A prontidão atual é **design-ready, execution-blocked**. O protocolo está especificado, mas a coleta confirmatória não deve começar enquanto o benchmark privado General Reasoning v1 e seu evaluator não estiverem disponíveis e auditados.

## Referências

[1]: https://www.anthropic.com/research/statistical-approach-to-model-evals — recomendações sobre análise pareada, agrupamento de erros e análise de poder em avaliações de modelos.

[2]: https://pmc.ncbi.nlm.nih.gov/articles/PMC3716987/ — Fagerland, Lydersen e Laake, estudo do McNemar para dados binários pareados.

[3]: https://arxiv.org/html/2409.17063v1 — estudo de benchmark de generalização de domínio com múltiplas tarefas e domínios não vistos.

[4]: GENERAL_REASONING_ROADMAP.md — regras experimentais, invariantes, métricas e stop conditions do UltronHarness.

[5]: GR2_SCIENTIFIC_EVALUATION.md — avaliação científica atual e limites da evidência do GR-2.
