# Plano de aceleração do Ultron

## Decisão de escopo

Não é possível prometer que um projeto local alcance **AGI em pouco tempo**. AGI não possui um teste único universalmente aceito, e uma arquitetura de controle, por si só, não converte automaticamente um modelo pequeno em inteligência geral. O objetivo executável de curto prazo é acelerar o Ultron rumo a um **agente geral útil, verificável e progressivamente mais capaz**, preservando a distinção entre capacidade demonstrada e hipótese de pesquisa.

> **Alvo operacional:** aumentar, em tarefas novas e de múltiplos domínios, a taxa de conclusão externamente verificada, a recuperação após falhas e a transferência de princípios verificados, sem aumentar permissões, sem vazar o evaluator e sem atribuir ao sistema um ganho que seja apenas mais chamadas ou mais tempo de inferência.

## O que realmente acelera

O gargalo atual não é apenas a existência de flags cognitivas. O Ultron já possui persistência, planejamento, memória, ferramentas limitadas, política, aprovação, observação, recuperação, false-stop recovery, reorientação e verified writeback. O gargalo de capacidade é a combinação entre **modelo-base pequeno**, ciclo de avaliação excessivamente lento e ausência de um loop curto de engenharia que consiga distinguir rapidamente uma melhoria real de uma resposta ocasionalmente boa.

O caminho de maior alavancagem é manter o plano de controle seguro e investir, nesta ordem, em modelo de desenvolvimento mais capaz, contexto e memória recuperados com proveniência, planejamento verificável, previsão antes da observação, recuperação de estado e avaliação rápida. O benchmark confirmatório continua separado e congelado; ele não deve ser usado como ambiente de tentativa e erro.

| Prioridade | Entrega | Evidência de sucesso | Limite preservado |
|---|---|---|---|
| 1 | Perfil `local-capable` com `qwen2.5:3b` para engenharia interativa | Tarefas de desenvolvimento mais difíceis podem ser exploradas sem mudar o default | Não altera o modelo confirmatório GR-1/GR-2 |
| 2 | Suíte rápida pública de capacidades, com tarefas sintéticas não privadas | Ciclos de minutos, métricas de planejamento, previsão, recuperação, memória e tool use | Não substitui validation/unseen privado |
| 3 | Avaliação de custo e latência por tarefa | Toda melhoria é comparada com chamadas, tokens, tempo e falhas | Evita chamar aumento de orçamento de ganho cognitivo |
| 4 | Integração incremental das capacidades cognitivas | Uma flag independente por capacidade, com ablação e testes adversariais | Shared orientation, OutcomeAuthority, segurança e writeback permanecem obrigatórios |
| 5 | Execução confirmatória somente após readiness | IC95, múltiplas seeds, unseen válido e ausência de leakage | Nenhum claim de generalização antes dos gates |

## Perfis de modelo

O perfil padrão continua igual para preservar compatibilidade e reprodutibilidade. Para o desenvolvimento interativo, o launcher agora oferece `local-capable`, que seleciona o `qwen2.5:3b` já instalado localmente. Esse perfil tende a ser mais lento que `qwen2.5:0.5b`, mas é uma base mais adequada para explorar raciocínio e planejamento. A seleção é operacional, não é evidência científica.

```powershell
# Desenvolvimento com menor latência
.\scripts\start.ps1 -ModelProfile local-fast

# Desenvolvimento com o modelo local mais capaz disponível
.\scripts\start.ps1 -ModelProfile local-capable
```

## Ciclo rápido de engenharia

Cada mudança cognitiva deve ser implementada como uma hipótese pequena. Primeiro, a capacidade é exercitada em uma suíte pública curta, com fixtures não privadas e resultados determinísticos. Em seguida, são executados testes comportamentais e adversariais. Só depois a capacidade pode entrar em uma coleta científica congelada. O modelo mais capaz de desenvolvimento não pode contaminar contratos, prompts, gold, evaluator ou dados do benchmark privado.

A primeira frente recomendada é completar e exercitar a cadeia **estado epistêmico → previsão → observação → atualização → recovery → verified writeback**. Essa cadeia é mais promissora que adicionar um novo controller paralelo, porque aumenta a qualidade das decisões sem retirar autoridade do executor, da Policy Engine ou da OutcomeAuthority. A segunda frente é reduzir o custo operacional por meio de checkpoint, execução limitada e cache de tarefas públicas, sem reduzir amostra ou trocar silenciosamente o protocolo confirmatório.

## Critérios para dizer que houve progresso

O Ultron só pode ser considerado melhor quando a melhora aparecer em tarefas novas, em mais de uma família, com o mesmo budget pareado ou com o custo explicitamente controlado. A análise deve incluir sucesso autoritativo, primeira tentativa, recuperação de false-stop, prediction accuracy, falsificação de premissas, backtracking recovery, calibração, chamadas, tokens, latência e segurança.

Um resultado positivo em uma demonstração isolada não é AGI. Um resultado positivo na suíte rápida é sinal de engenharia. Um resultado positivo na validation privada é evidência intermediária. Somente um resultado que sobreviva aos splits inéditos, múltiplas seeds, IC95, controle de custo, ablações e auditoria de leakage pode sustentar uma afirmação limitada de ganho de generalização — nunca uma declaração automática de AGI.

## Próxima execução

A próxima implementação deve criar a suíte rápida pública e o seu runner resumível, reutilizando os mesmos contratos de telemetria e OutcomeAuthority, mas sem ler o benchmark privado. O runner precisa emitir artefatos sanitizados, suportar `--max-new-variants`, registrar cada chamada e falha, e terminar em poucos minutos. Em paralelo, a validation privada permanece pausada até que a nova geração truly private-only do unseen seja auditada e congelada.

O objetivo não é fazer o Ultron parecer mais inteligente em uma resposta. É tornar cada iteração **mais capaz, mais rápida de medir e mais difícil de enganar**.
