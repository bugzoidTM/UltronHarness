# Avaliação científica do GR-2

## Resumo executivo

O GR-2 — *Prediction Before Observation* — está **operacionalmente implementado e metodologicamente instrumentado**, mas ainda não possui evidência suficiente para sustentar uma afirmação de ganho cognitivo, maior capacidade de generalização ou melhora estatisticamente significativa. O piloto privado disponível contém uma única missão, um único seed e o modelo `local-fallback`; portanto, deve ser interpretado como um teste de encanamento e validade do contrato, não como avaliação confirmatória.

A conclusão científica atual é **inconclusiva, sem evidência positiva de generalização**. A flag deve permanecer desligada por padrão até a execução de um protocolo pareado, com o mesmo modelo-base efetivo do GR-0, múltiplas seeds, famílias privadas inéditas, evaluator independente e análise estatística congelada antes da consulta aos resultados.

> O que foi demonstrado é que o sistema consegue registrar uma previsão antes da ação e associá-la a uma observação posterior sem romper os contratos de segurança. Ainda não foi demonstrado que essa capacidade melhora a resolução de problemas novos.

## Evidência disponível

| Fonte | Escopo | Resultado | Interpretação científica |
|---|---|---|---|
| GR-0 congelado | 3 missões, 3 modos, seed 53, `qwen2.5:0.5b`, evaluator privado | `measurement_valid=true`; ATC 0 nos modos | Baseline metodologicamente válido |
| GR-2 pareado | 1 missão, 3 modos, seed 53, `local-fallback`, evaluator privado | `measurement_valid=true`; 1 previsão observada; ATC 0 | Instrumentação válida; amostra insuficiente |
| Baseline pareado | Mesma missão, seed, modelo e evaluator, GR-2 desligado | `measurement_valid=true`; 0 previsões; ATC 0 | Controle de isolamento da flag |
| Suíte automatizada | Testes unitários, comportamentais, adversariais e regressão | 189 testes aprovados; cobertura 77,03% | Evidência de funcionamento do produto |
| Segurança e E2E | Segurança Windows e smoke local | 12 aprovados, 1 ignorado; smoke aprovado | Ausência de regressão operacional observada |

No piloto GR-2, a previsão ocorreu no modo `full_plan`, foi criada antes da ação e recebeu `confirm` após a verificação. Os modos `short_horizon` e `next_action` não produziram uma ação executada naquela missão; por isso, a ausência de previsões nesses modos não deve ser interpretada como ausência de capacidade em geral.

A métrica de `prediction_accuracy` do piloto é uma **concordância instrumental** entre a classificação registrada e a verificação interna da ação. Ela não é ainda uma medida independente de acurácia preditiva: a expectativa é derivada do contrato/ação, e não de um conjunto privado de previsões cujo rótulo de acerto esteja separado do verificador de execução. A avaliação confirmatória deve resolver essa limitação com rótulos privados de outcome e métricas definidas antes do acesso aos resultados.

## Hipótese e estimando

A hipótese confirmatória será:

> Mantendo o mesmo modelo-base, seed, orientação, contrato de missão, ferramentas, budget e evaluator, ativar Prediction Before Observation aumenta a taxa de conclusão externa autoritativa em famílias privadas inéditas, em comparação com o GR-1 com estado epistêmico ligado e previsão desligada.

O estimando primário será a diferença pareada média entre as variantes em cada unidade missão-seed, agregada por família privada. Para a unidade `i`, define-se `D_i = Y_GR2,i − Y_GR1,i`, em que `Y` vale 1 somente quando o evaluator privado confirma a conclusão final com a autoridade exigida. O resultado primário será a média de `D_i` no conjunto confirmatório de famílias unseen.

A hipótese nula é `E[D] = 0`. O efeito mínimo de interesse deve ser fixado antes da coleta em **5 pontos percentuais de ATC**, salvo justificativa documentada em uma revisão prévia do protocolo. Um resultado só poderá ser chamado de positivo se o intervalo de confiança de 95% do efeito excluir zero, o efeito pontual superar o limiar mínimo de interesse e o ganho não estiver concentrado em uma única família.

## Métricas pré-especificadas

| Prioridade | Métrica | Definição |
|---|---|---|
| Primária | ATC incremental | Diferença na fração de missões com PASS externo autoritativo, GR-2 menos GR-1 |
| Secundária | First-pass success | PASS na primeira conclusão, sem false-stop recovery |
| Secundária | False-stop recovery | Falha externa seguida de estratégia/ação diferente e PASS externo |
| Secundária | Prediction accuracy independente | Concordância entre a classe esperada privada e o outcome observado, sem usar apenas o mesmo verifier que gerou a classificação |
| Secundária | Assumption falsification rate | Premissas falsas relevantes identificadas e testadas antes da conclusão |
| Secundária | Calibration error | Erro absoluto/Brier entre confiança antes/depois e outcome privado observado |
| Segurança | Invalid rate | Fração de traces com violação de contrato, leakage, evaluator error ou atribuição inválida |
| Custo | Eficiência | ATC por chamada LLM, token, ação, latência e custo pareado |
| Diagnóstica | SDV | Decisões estruturadas válidas ao final dividido pelo total |

A análise não deve transformar previsões pendentes em falhas cognitivas automaticamente. Traces com falha de infraestrutura são classificados como inválidos e reportados separadamente; falhas de decisão, ações rejeitadas e ausência de PASS externo permanecem resultados válidos da variante.

## Análise estatística

A comparação principal será pareada por missão e seed, com a mesma orientação compartilhada. A unidade de reamostragem primária será a **família de tarefas**, porque missões dentro de uma família compartilham estrutura e não podem ser tratadas como observações independentes. Será reportada a diferença média, o intervalo de confiança de 95% por bootstrap agrupado em família, o número de famílias, missões e seeds e a tabela de pares concordantes/discordantes.

Como análise de sensibilidade para o outcome binário pareado, será reportado o teste de McNemar, preferencialmente na forma mid-*p* ou exata conforme o regime amostral. Métodos para dados pareados devem respeitar a dependência entre os resultados das duas variantes; o McNemar foi estudado especificamente para proporções binárias em pares correspondentes [2]. A recomendação de analisar diferenças pareadas, agrupar erros quando há clusters e realizar análise de poder antes da coleta é consistente com boas práticas recentes para avaliações de modelos [1].

A métrica primária terá um único teste confirmatório bilateral com `alpha=0,05`. Métricas secundárias serão tratadas como análises exploratórias ou terão correção de múltiplas comparações por Benjamini–Hochberg, com o procedimento escolhido congelado antes da abertura dos resultados. Não serão selecionadas métricas retrospectivamente com base no maior efeito observado.

## Validade e limitações

A validade externa dependerá de famílias que não tenham participado da elaboração de prompts, thresholds, exemplos, regras de roteamento, seleção de missões ou análise exploratória. A avaliação de generalização deve modelar explicitamente a mudança de distribuição entre famílias; benchmarks de generalização de domínio destacam que o desempenho em dados não vistos pode degradar sob mudanças de distribuição e que a definição de domínio e os splits precisam ser controlados [3].

A validade interna exige que o baseline e o candidato recebam a mesma orientação congelada, workspace inicial, allowlist, budget, seed, modelo efetivo e evaluator. A ordem de execução das variantes pode ser randomizada após a orientação, mas cada variante deve operar em uma cópia isolada do mesmo fixture. O evaluator privado deve permanecer fora do repositório e fora dos prompts, snapshots, eventos e relatórios públicos.

O principal risco atual é **subpotência**, não invalidade: uma missão não permite estimar um efeito de generalização. O segundo risco é de **circularidade da métrica**, pois a classificação atual é derivada da verificação operacional. O terceiro é de **confundimento de modelo**, pois o piloto GR-2 usou `local-fallback`, enquanto o GR-0 congelado válido usou `qwen2.5:0.5b` via alias `ollama`. Nenhuma conclusão de efeito deve misturar esses regimes.

## Decisão científica atual

| Critério | Estado |
|---|---|
| Instrumentação expected/observed | Aprovada |
| Isolamento da feature flag | Aprovado |
| Segurança e writeback | Sem regressão observada |
| Validade dos pilotos | Aprovada para os dois artefatos |
| Evidência de ganho de ATC | Não demonstrada |
| Evidência de generalização unseen | Não coletada |
| IC95 do efeito | Não estimado de forma confirmatória |
| Promoção científica do GR-2 | Não autorizada |

A próxima decisão correta é executar o plano pré-registrado de generalização anexado separadamente. A flag continuará desligada por padrão até que esse protocolo seja aprovado, os ativos privados estejam congelados e o gate de validade seja concluído.

## Referências

[1]: https://www.anthropic.com/research/statistical-approach-to-model-evals — *A statistical approach to model evaluations*, recomendações sobre diferenças pareadas, erros agrupados e análise de poder.

[2]: https://pmc.ncbi.nlm.nih.gov/articles/PMC3716987/ — Fagerland, Lydersen e Laake, *The McNemar test for binary matched-pairs data*.

[3]: https://arxiv.org/html/2409.17063v1 — Zamanitajeddin et al., *Benchmarking Domain Generalization Algorithms in Computational Pathology*.

[4]: GENERAL_REASONING_ROADMAP.md — roadmap experimental aprovado do UltronHarness.

[5]: GR2_IMPLEMENTATION_REPORT.md — relatório operacional do GR-2 e artefatos do piloto.
