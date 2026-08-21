# Auditoria de Reutilização Externa — UltronLocal

## Origem e escopo

A auditoria foi feita por leitura de metadados e arquivos públicos do repositório [bugzoidTM/UltronLocal](https://github.com/bugzoidTM/UltronLocal), sem clonar, executar ou incorporar código externo. Na consulta realizada, o repositório era público, tinha branch padrão `main`, linguagem predominante TypeScript e **não declarava licença** (`license: null`). A ausência de licença impede a cópia/adaptação direta de código até que haja uma licença explícita compatível ou autorização do titular.

## Achados relevantes

O repositório contém uma árvore muito grande, incluindo dependências `node_modules` versionadas, múltiplos Dockerfiles, scripts de auto-healing, loops autônomos em segundo plano, self-improvement e componentes de persona/voz. Esses elementos não são compatíveis com o escopo congelado do PRD v0.3 e tampouco devem ser executados localmente sem auditoria específica.

Foram lidos estaticamente os módulos `context_metrics.py`, `context_policy.py` e `benchmark_correlation.py`. O primeiro usa uma estimativa simples de tokens por comprimento (`len(serialized)/4`) e persiste JSONL. O segundo define perfis explícitos de fonte e orçamento de contexto. O terceiro mede correlação de patches promovidos chamando uma suíte externa, o que não é apropriado para o UltronPro porque mistura auto-patches e execução não isolada.

## Decisão de aproveitamento

| Componente externo | Decisão | Justificativa |
|---|---|---|
| Ideia de métrica leve de tokens | **Referenciar como ideia; implementar próprio** | A abordagem é simples, mas o PRD requer métricas por bloco e persistência vinculada a research runs. A implementação local foi criada sem copiar código. |
| Perfis de orçamento de contexto | **Referenciar como ideia; adaptar conceito próprio** | A noção de bloco/orçamento é útil para CTX-2. O UltronPro adotará `ContextBudgeter` e feature flags próprios, testáveis e sem dependências externas. |
| Correlação de patches/benchmark | **Rejeitar** | Depende de auto-patches promovidos e suíte externa; contraria a proibição de self-editing e não isola variáveis. |
| Loops de autonomia, reflexão, judge e self-improvement | **Rejeitar** | Estão fora do escopo congelado do Project Prometheus e introduzem variáveis não controladas. |
| Persona, voz, phenomenal/qualia | **Rejeitar** | Explicitamente fora de escopo; não responde à hipótese CGFE. |
| Dockerfiles, Puppeteer bridge e dependências versionadas | **Rejeitar** | Sem benefício direto à medição do CGFE; aumentam superfície de ataque e manutenção. |
| Cache semântico e ledger de competência | **Pendente de auditoria posterior** | Podem conter conceitos úteis, mas não serão copiados sem licença, testes isolados e hipótese mensurável associada. |

## Conclusão

Nenhum código do UltronLocal será incorporado enquanto o repositório não declarar licença reutilizável. O valor aproveitado nesta etapa é exclusivamente conceitual: instrumentação de contexto e políticas explícitas de orçamento, reimplementadas de forma mínima no UltronPro sob testes locais. A referência externa não altera os controles de segurança, a política de resultados negativos ou a proibição de autoedição.
