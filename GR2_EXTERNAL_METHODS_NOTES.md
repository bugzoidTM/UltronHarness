# Referências metodológicas externas consultadas

## [1] Anthropic — A statistical approach to model evaluations
URL: https://www.anthropic.com/research/statistical-approach-to-model-evals

Pontos usados no protocolo: avaliações devem reportar incerteza; diferenças pareadas reduzem variância quando as mesmas questões são usadas nas variantes; erros-padrão devem considerar clusters quando questões relacionadas compartilham estrutura; e análise de poder deve ser planejada antes da coleta. A recomendação é reportar diferenças, erros, intervalos de confiança, correlações e tamanho amostral/poder, em vez de apenas scores agregados.

## [2] Fagerland, Lydersen e Laake — The McNemar test for binary matched-pairs data
URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC3716987/
DOI: https://doi.org/10.1186/1471-2288-13-91

Pontos usados no protocolo: o outcome binário em pares correspondentes requer métodos que respeitem a dependência; o artigo compara versões assintóticas, exatas e mid-p do teste de McNemar e discute o comportamento em amostras pequenas e moderadas.

## [3] Zamanitajeddin et al. — Benchmarking Domain Generalization Algorithms in Computational Pathology
URL: https://arxiv.org/html/2409.17063v1

Pontos usados no protocolo: generalização deve ser avaliada sob mudanças de distribuição e em domínios não vistos; benchmarks robustos precisam explicitar domínios, tarefas, splits e procedimentos de validação, evitando confundir desempenho no domínio observado com generalização para targets inéditos.

## Referências locais

- `GENERAL_REASONING_ROADMAP.md`
- `GR2_IMPLEMENTATION_REPORT.md`
- `GR2_SCIENTIFIC_EVALUATION.md`
- `GR2_GENERALIZATION_PROTOCOL.md`
- `GR2_GENERALIZATION_MANIFEST.json`
