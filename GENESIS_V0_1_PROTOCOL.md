# Project Genesis v0.1 — Protocolo Bounded

## Objetivo

Verificar se o Ultron consegue **compor autonomamente um programa temporário de raciocínio** a partir de primitivas cognitivas públicas, selecionar o programa com base em desempenho diagnóstico e testá-lo em holdout público que não participou da criação ou seleção.

O resultado deste protocolo é evidência de mecanismo de engenharia. Não é um teste de AGI, não mede consciência ou vontade forte e não sustenta alegações de generalização ampla.

## Delimitação congelada

| Item | Regra |
|---|---|
| Diagnóstico | Exatamente `reasoning_01` e `reasoning_02`, tarefas públicas do UGIB-Lite. |
| Holdout | Exatamente `reasoning_06` e `reasoning_07`, tarefas públicas não usadas no diagnóstico. |
| Programas | O modelo pode gerar de 1 a 3 Cognitive Programs; nenhum programa é selecionado de catálogo fechado. |
| Programa | Cada programa tem de 1 a 6 operadores da lista pública de primitivas. |
| Primitivas | `OBSERVE`, `IDENTIFY_UNKNOWN`, `REPRESENT`, `DECOMPOSE`, `HYPOTHESIZE`, `COMPARE`, `PREDICT`, `TEST`, `DEDUCT`, `BACKTRACK`, `VERIFY`, `UPDATE_BELIEF`, `STOP`. |
| Modelo | O mesmo modelo efetivo em síntese, diagnóstico e holdout. O nome efetivo é registrado. |
| Seed | Uma única seed fixa, registrada em todos os runs. Não há múltiplas seeds. |
| Budget | Mesmo `max_tokens`, timeout por tarefa, limite de passos e allowlist em baseline, candidatos e holdout. |
| Execução | Baseline diagnóstico: 2; candidatos diagnósticos: no máximo 6; baseline holdout: 2; vencedor holdout: 2. Total máximo: 12 tarefas, além de uma chamada de síntese. |
| Tempo | Timeout total configurável, limitado a 600 segundos; default do probe: 540 segundos. |
| Leakage | O sintetizador recebe objetivos, respostas e erros observados, mas nunca recebe gold, expected outputs, private specs ou respostas do holdout. |
| Segurança | O programa é interpretado apenas como sequência de instruções textuais. Não executa Python, shell, Git, rede, escrita de arquivos, alteração de permissões ou alteração de código. |
| Seleção | O vencedor é escolhido automaticamente pela média diagnóstica, com desempate determinístico pela ordem de geração. Não existe parâmetro humano para escolher o programa. |
| Holdout | O holdout é executado somente depois da seleção e não retorna dados ao sintetizador. |
| Promoção | NCPG positivo, ausência de regressão por tarefa, evidência suficiente e contratos invariantes são necessários. Promoção usa exclusivamente `OutcomeAuthority` e `VerifiedWritebackGate`. |
| Falha | Empate, regressão, timeout, output inválido, programa inválido, divergência de modelo/seed/budget/allowlist, leakage ou evidência insuficiente resultam em `rejected`. |

## Interpretação

A métrica do probe é:

```text
NCPG = score(winner, holdout) - score(baseline, holdout)
```

Um NCPG positivo no microprobe seria uma evidência inicial de que a combinação gerada pelo modelo alterou o comportamento do mesmo modelo em tarefas públicas não usadas na criação. Ainda seria necessário replicar o resultado com protocolo confirmatório, múltiplas seeds e holdouts realmente independentes antes de qualquer claim científico.

O Genesis v0.1 não implementa recombinação entre programas, não executa autoedição de código, não acessa benchmark privado e não inicia o ciclo seguinte automaticamente.
