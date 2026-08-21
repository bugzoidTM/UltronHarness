# Project Athena — Relatório de Diagnóstico Científico

**Produto:** UltronPro local-first  
**Escopo:** consolidação cognitiva, seleção de experiência e reuso seguro  
**Estado:** implementação concluída; componentes cognitivos permanecem em **shadow mode** salvo onde indicado como experimento de pesquisa.

## Pergunta de pesquisa

> **O UltronPro consegue aprender qual experiência usar, quando usá-la e quando ignorá-la?**

A evidência obtida permite uma resposta **parcial e delimitada**. O sistema demonstrou que procedimentos selecionados por família podem aumentar desempenho futuro em um benchmark de transferência processual. Ele também demonstrou que simplesmente aumentar a quantidade de experiências admitidas não elevou o desempenho no protocolo LEARN-2. Portanto, o UltronPro já possui evidência de **seleção útil em domínios específicos**, mas ainda não demonstrou uma lei geral de escala de experiência nem uma política de reuso universalmente promotável.

| Dimensão | Evidência observada | Decisão |
|---|---:|---|
| CGFE-10 | fresh 0,712; experienced 0,720; média +0,008 em 10 seeds | Positivo, porém fraco; IC95% inclui zero |
| Transfer-20 factual | TG médio -0,1167 em 3 seeds | Rejeitado e preservado como controle negativo |
| Transfer-20 processual v2 | TG médio **+0,266667**; IC95% [+0,234000, +0,299333] em 3 seeds | Gate Athena-3 aprovado como evidência inicial |
| LEARN-2 | CGFE 0,000 em N=0/10/50/100/200; -0,020 em N=25 | CG-2 não aprovado; sem promoção por escala |
| Symbolic Lane | 100% no contrato aritmético determinístico de teste | Mantém shadow até telemetria representativa |
| World Model, critic e política | Testes determinísticos aprovados | Shadow; nenhuma alteração de plano ou bloqueio |

## Protocolo e controles

O protocolo usa execução local com o modelo de pesquisa `ollama_research` e seed explicitamente propagada ao runtime. Tarefas públicas, contratos privados e corpus de experiência permanecem separados. O corpus de transferência processual contém apenas princípios abstratos de decisão, sem objetivos, respostas, fixtures, nomes de artefatos ou comandos do domínio-alvo. O avaliador compara deterministicamente a sequência de ações produzida com o contrato privado.

O primeiro Transfer-20 continha perguntas factuais e não apresentou espaço de ganho real para reuso procedural. Essa configuração foi mantida intacta como resultado negativo. A versão v2 a substituiu apenas como novo experimento, usando vinte casos públicos distribuídos entre validação estruturada, recuperação de dependências, recuperação de estado e planejamento.

## Resultado de transferência processual

| Seed | Fresh | Experienced | Transfer Gain |
|---:|---:|---:|---:|
| 42 | 0,200 | 0,450 | +0,250 |
| 43 | 0,200 | 0,450 | +0,250 |
| 44 | 0,200 | 0,500 | +0,300 |
| **Média** | **0,200** | **0,466667** | **+0,266667** |

O ganho não foi homogêneo. Recuperação de dependências apresentou ganho médio de +0,933333 e validação estruturada +0,333333. Recuperação ficou em 0,000000, enquanto planejamento foi -0,200000. A interpretação correta não é que toda memória procedimental ajuda, mas que **uma experiência procedural compatível pode ser selecionada com benefício mensurável em determinadas famílias**. As famílias neutra e negativa não foram promovidas.

## Governança e módulos Athena

| Componente | Implementação | Proteção de segurança | Estado |
|---|---|---|---|
| Memory Governor | MAS: evidência, generalização, novidade, utilidade e confiança | bloqueia conteúdo privado, duplicado ou sem evidência | Experimental |
| Skill Governor | health por sucesso, utilidade, confiança e recência | sem apagamento automático do histórico | Experimental |
| Self Model | posterior Beta, score calibrado e incerteza | não usa estados subjetivos | Experimental |
| Symbolic Lane | AST whitelist, fatos e regras explícitas | sem `eval`; roteamento conservador | Shadow |
| World Model | previsão por frequência com smoothing | não bloqueia ações nem altera planos | Shadow |
| Evidence Critic | prioriza teste, schema, arquivo e exit code | LLM critic apenas sem verificador determinístico | Shadow |
| Counterfactual e Strategy Policy | ranking por evidência observada e domínio compatível | não executa nem replaneja | Shadow |

A integração do repositório UltronLocal seguiu a regra de portabilidade: nenhuma linha de código foi copiada. Os algoritmos foram reimplementados contra as interfaces locais e a auditoria de proveniência foi preservada em `data/artifacts/research/ports/athena_governors_port.md`.

## LEARN-2: resultado de escala

O LEARN-2 usou uma baseline fresh pareada e um pool de 200 procedimentos curados, verificados pelo Memory Governor e distribuídos por categoria. A curva não mostra benefício por quantidade para esta configuração.

| N de experiências | Fresh | Experienced | CGFE |
|---:|---:|---:|---:|
| 0 | 0,680 | 0,680 | +0,000 |
| 10 | 0,680 | 0,680 | +0,000 |
| 25 | 0,680 | 0,660 | -0,020 |
| 50 | 0,680 | 0,680 | +0,000 |
| 100 | 0,680 | 0,680 | +0,000 |
| 200 | 0,680 | 0,680 | +0,000 |

Esse resultado rejeita a hipótese simples de que maior volume de experiências admitidas produz, por si, maior capacidade. Ele reforça a decisão de não habilitar writeback ou seleção ampla como padrão sem efeito empírico específico.

## Painel e qualidade operacional

O Dashboard Research v3 expõe Learning, Self Model, Memory & Skills, World Model e Transfer a partir de SQLite e dos artefatos de pesquisa locais. A API não transforma métricas em decisões de promoção; seu papel é tornar a evidência auditável.

| Gate | Resultado |
|---|---|
| Testes determinísticos com cobertura | 36 passed; cobertura 73,15% |
| Segurança Windows | 12 passed; 1 skipped |
| Testes de agente | 9 passed; 1 xfailed |
| Lint | `ruff` aprovado |
| Build React | aprovado |
| Smoke API/UI | aprovado |

## Conclusão

O UltronPro ultrapassou o estágio de mera acumulação de texto em uma condição experimental delimitada: o Transfer-20 processual mostrou ganho de transferência positivo quando uma estratégia procedural abstrata foi selecionada para uma família compatível. Isso satisfaz a evidência inicial do gate Athena-3 e é mais significativo que o CG-1 isolado.

Ao mesmo tempo, o sistema **não** demonstrou que todo conjunto de experiências governadas melhora o desempenho, pois o LEARN-2 foi neutro com uma regressão pontual. A conclusão operacional é deliberadamente conservadora: usar seleção de experiência apenas onde o benchmark revelou ganho, manter módulos cognitivos em shadow mode e preservar tanto os resultados positivos quanto os negativos para a próxima iteração.

## Artefatos de auditoria

| Artefato | Finalidade |
|---|---|
| `data/artifacts/research/transfer20_initial_findings.md` | Controle negativo factual do Transfer-20 |
| `data/artifacts/research/transfer20_procedural_multiseed.json` | Síntese multiseed do Transfer-20 processual v2 |
| `data/artifacts/transfer/` | Rastros por tarefa das condições fresh e experienced |
| `data/research/hypotheses.jsonl` | Registro append-only de hipóteses |
| `ATHENA_PROGRESS.md` | Checkpoint operacional do projeto |
| `data/artifacts/research/ports/athena_governors_port.md` | Auditoria de reuso e proveniência |
