# Transfer-100 v3 — Resultado Consolidado

## Protocolo executado

O Transfer-100 v3 foi executado com o modelo local `ollama_research` (`qwen2.5:3b`) nas seeds pareadas **42, 43 e 44**. Cada uma das 100 tarefas públicas foi chamada individualmente com `max_tokens=16`; os contratos permaneceram no diretório externo `UltronHarness_private/transfer100_v3`, fora do repositório. Foram avaliadas três condições: **Never Inject**, **Always Inject** e o roteador Hermes **USE/ABSTAIN/REJECT**. O controle batched foi realizado separadamente na seed 42 e não foi agregado às métricas per-task.

| Condição per-task | Média | IC 95% | Ganho vs. Never |
|---|---:|---:|---:|
| Never Inject | 0,216667 | 0,203600–0,229733 | — |
| Always Inject | 0,283333 | 0,276800–0,289867 | +0,066667 |
| Router USE/ABSTAIN/REJECT | 0,216667 | 0,203600–0,229733 | +0,000000 |

## Interpretação

O roteador Hermes foi exercitado no protocolo real e decidiu conservadoramente **ABSTAIN** quando não havia utilidade pareada suficiente. Como consequência, o resultado do Router coincidiu com Never Inject, sem injeção experimental não justificada. Isso confirma a integração da política no harness, mas **não demonstra ainda ganho de transferência do Router**.

A condição Always Inject obteve ganho médio positivo agregado, porém com custo mensurável. A **Abstention Value** foi **−0,066667**, pois o Router não capturou o ganho do Always; e a **Harmful Retrieval Rate** do Always foi **0,093333**. A análise por família torna essa cautela obrigatória: Always elevou `structured_validation` e `dependency_recovery`, mas reduziu `state_recovery` de aproximadamente 0,316667 para 0,000000 e não melhorou `planning`.

| Métrica de segurança | Resultado | Decisão operacional |
|---|---:|---|
| Router Transfer Gain | 0,000000 | Não promover famílias |
| Abstention Value | −0,066667 | Não inferir benefício seletivo ainda |
| Harmful Retrieval Rate — Always | 0,093333 | Always permanece proibido no runtime |
| Controle batched — seed 42 | Fresh 0,000000; Always 0,100000 | Diagnóstico de formato, não comparável ao resultado per-task |

> **Gate Hermes v3: `SHADOW_RETAINED_NO_PROMOTION`.** O roteador está conectado e auditável, mas nenhuma família entra no contexto ativo até existir evidência pareada suficiente e uma promoção explícita no `family_utility_map`.

## Convergência com o runtime

O runtime passou a classificar cada tarefa, persistir a assinatura, avaliar experiências candidatas, registrar `routing_decisions` e injetar procedimentos somente para decisões `USE` de famílias no estado `PROMOTABLE`. A ausência de famílias promovidas neste resultado faz o comportamento em produção permanecer **fresh context por padrão**, o que evita repetir o dano observado em `state_recovery`.

Em paralelo, o benchmark `e2e_long_runtime_v1` concluiu os cinco cenários determinísticos de projeto local. A taxa de conclusão foi **1,0000**, a taxa de recuperação foi **1,0000**, a média de passos executados foi **12,60** e a média de replanejamentos foi **1,00**. Esses cenários validam a mecânica de replanejar, verificar por predicados determinísticos e finalizar artefatos; não são uma alegação de capacidade generativa do modelo.

## Próxima evidência exigida

O próximo experimento deve alimentar `experience_pair_utility` com resultados pareados externos ao alvo, para que o Router possa emitir `USE` sob a mesma política que o runtime aplica. Uma eventual promoção deve exigir, por família, no mínimo três observações, média de delta maior ou igual a 0,10 e limite inferior do IC 95% positivo, conforme o `NegativeTransferFirewall`. Até então, o produto permanece corretamente em modo de abstinência seletiva.
