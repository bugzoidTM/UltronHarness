# Transfer-100 — seed 42 preliminar

A primeira execução estável do `transfer100-v1` usou `ollama_research`, seed 42 e limite de 16 tokens de saída por tarefa. A condição fresh marcou 0,070; a condição experienced marcou 0,180; o Transfer Gain observado foi **+0,110**.

Este resultado é apenas preliminar e não satisfaz Hermes Gate 1. A rodada de dez seeds permanece obrigatória; resultados positivos, nulos ou negativos serão preservados.

| Família | TG observado |
|---|---:|
| structured_validation | +0,500 |
| configuration_repair | +0,050 |
| dependency_recovery | 0,000 |
| state_recovery | 0,000 |
| planning | 0,000 |
