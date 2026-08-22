# Auditoria de atribuição de modelo — Forge E2E

A consulta das tarefas com `workspace LIKE 'forge_%'` e seus registros em `model_calls` confirmou a falha de atribuição identificada na revisão.

| Item | Evidência observada |
|---|---|
| Missão E2E | `Reparar módulo Python mínimo` |
| Modelo efetivamente registrado | `qwen2.5:0.5b` |
| Parâmetro registrado pelo runner | `ollama_research` |
| Conclusão | O parâmetro do runner não selecionava o modelo usado pelo `ModelGateway`; portanto, a execução E2E anterior **não pode ser atribuída ao qwen2.5:3b**. |

A evidência `ATC = 0` anterior permanece válida apenas como resultado do caminho de execução então configurado. Ela está contaminada para qualquer interpretação sobre a capacidade do modelo de 3B e será substituída por uma execução que registra e verifica a identidade efetiva do modelo antes de calcular o resultado.
