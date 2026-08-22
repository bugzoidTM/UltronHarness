# Auditoria de reparo estruturado — Forge E2E

## Escopo

A auditoria identificou que o planejador chamava `ModelGateway.generate(..., json_mode=True)` e validava a resposta diretamente com `Plan.model_validate_json(...)`. Qualquer erro de sintaxe JSON ou de schema levava imediatamente ao fallback, embora o gateway já tivesse um mecanismo de reparo estruturado.

A correção substitui esse caminho por `ModelGateway.structured(Plan, ...)`. A primeira resposta passa pela validação Pydantic; se não for válida, o gateway reenvia a resposta ao mesmo modelo com a solicitação de correção e tenta a validação uma segunda vez. A `seed` e o alias do modelo são propagados para ambas as chamadas.

| Controle | Implementação |
|---|---|
| Modelo | O planejador informa explicitamente `model_name=self.models.primary_name`. |
| Seed | `planning_seed` é encaminhada à primeira chamada e à tentativa de reparo. |
| Telemetria | A primeira geração é persistida como `purpose = planning`; a correção, quando ocorrer, como `purpose = planning_repair`. |
| Atribuição | O runner verifica modelo e seed em **todas** as chamadas de planejamento, não apenas na primeira. |
| Validade | A medida continua inválida se o plano final não vier de `model_structured`. |

## Segurança e protocolo E2E

O fallback do runtime geral mantém `file.write` em risco R2, preservando o fluxo de aprovação e a Política de Autonomia. No Forge E2E, o `ToolRegistry` é reduzido previamente à allowlist pública da missão; como `file.write` não integra essa allowlist, o fallback somente pode usar `python.execute` em R1. Assim, o benchmark não introduz uma aprovação artificial ao cair no fallback, sem relaxar o comportamento supervisionado da plataforma fora do benchmark.

## Validação controlada

Foi executada uma missão pública do Forge E2E com `ollama_research` (`qwen2.5:3b`) e seed `50`. A tentativa inicial e a tentativa de reparo foram ambas atribuídas ao modelo e à seed corretos. O reparo foi realmente acionado, mas não produziu um `Plan` válido; portanto, o resultado permanece inelegível para inferência sobre capacidade ou ATC.

| Campo | Evidência da execução |
|---|---:|
| Missão | `forge_e2e_01` |
| Modelo configurado e efetivo | `qwen2.5:3b` |
| Seed configurada e efetiva | `50` |
| Chamadas de planejamento | `2` |
| Reparo estruturado tentado | `true` |
| Atribuição de modelo verificada | `true` |
| Atribuição de seed verificada | `true` |
| Origem final do plano | `fallback_after_model_error` |
| Aprovação artificial no E2E | `0` |
| Validade de medição | `false` |

> O reparo elimina a hipótese de que o fallback observado seja causado exclusivamente pela ausência desse mecanismo. A falha residual agora está limitada de forma mais precisa: para este prompt e esta missão, o `qwen2.5:3b` não entregou um `Plan` Pydantic válido após duas tentativas determinísticas com o mesmo modelo e a mesma seed. Isso não sustenta uma conclusão sobre incapacidade E2E; apenas impede a medição até que o planejamento estruturado seja obtido.

## Quality gates

A alteração foi validada com **95 testes aprovados**, cobertura de ramos de **77,97%** e lint sem violações. As regressões cobrem propagação de modelo e seed na tentativa de reparo, persistência de `planning_repair`, contagem de chamadas LLM, manutenção das aprovações supervisionadas e respeito à allowlist isolada do Forge E2E.
