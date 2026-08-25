# Estado da aceleração do Ultron

## Conclusão executiva

A primeira aceleração concreta foi entregue: o Ultron agora possui um perfil local de desenvolvimento com o modelo `qwen2.5:3b`, perfis cognitivos opt-in para GR-1 e GR-1+GR-2, e um probe público curto, resumível e com limite de variantes. O default, as permissões, o evaluator privado e o modelo confirmatório congelado permanecem inalterados.

Isso **não é AGI** e não é uma medição de generalização. É uma melhoria do ciclo de engenharia: ficou possível testar capacidades com mais rapidez, checkpoint e rastreabilidade, usando uma base local mais capaz quando o objetivo é desenvolvimento.

## Alterações entregues

| Área | Alteração | Default preservado |
|---|---|---|
| Modelo de desenvolvimento | `scripts/start.ps1 -ModelProfile local-capable` seleciona o alias local `ollama_research`, configurado para `qwen2.5:3b` | Sim; sem perfil, a configuração original continua ativa |
| Cognição experimental | `-CognitionProfile gr1` ativa somente `epistemic_state`; `gr1-gr2` ativa também `prediction_before_observation` | Sim; todas as flags continuam desligadas sem perfil |
| Avaliação rápida | `scripts/run_capability_probe.py` usa apenas tarefas públicas, checkpoint atômico, `--max-new-variants`, dry-run e resumo sanitizado | Sim; não acessa o benchmark privado GR |
| Documentação | `AGI_ACCELERATION_PLAN.md` e este relatório registram alvo, limites e interpretação | Sim; nenhum claim científico foi promovido |
| Robustez do planejamento | O orquestrador agora rejeita semanticamente planos com ferramenta inexistente, ferramenta fora do contrato ou argumentos obrigatórios ausentes, acionando o fallback auditável | Sim; não amplia permissões nem altera a OutcomeAuthority |

## Sinal público observado

Foi executado o mesmo probe público difícil em oito tarefas e duas variantes (`baseline` e `ultron-fresh`), com seed 43. Os artefatos completos, sanitizados e development-only estão em `data/artifacts/research/capability_probe/`.

| Modelo | Variante | Sucessos | Score médio | Latência média |
|---|---|---:|---:|---:|
| `qwen2.5:0.5b` | baseline | 1/8 | 0,125 | 912 ms |
| `qwen2.5:0.5b` | ultron-fresh | 4/8 | 0,500 | 678 ms |
| `qwen2.5:3b` | baseline | 3/8 | 0,375 | 1.401 ms |
| `qwen2.5:3b` | ultron-fresh | 4/8 | 0,500 | 1.533 ms |

O resultado é útil para priorização, mas não autoriza concluir que o modelo 3B ou o GR-1/GR-2 produz ganho geral. A amostra é pequena, pública, de uma única seed, e o modelo e a variante não devem ser tratados como fatores independentes a partir desse probe. O resultado mais importante é operacional: o ciclo curto funciona e revela rapidamente que as falhas restantes estão concentradas em raciocínio quantitativo específico e classificação de recuperação, que devem orientar a próxima hipótese de engenharia.

## Correção encontrada no primeiro smoke acelerado

O primeiro smoke com `qwen2.5:3b` e GR-1+GR-2 opt-in revelou um problema real de robustez do plano: a saída estruturada podia ser formalmente JSON válido, mas ainda assim inventar uma ferramenta ou usar argumentos incompatíveis com o registro de ferramentas. Isso provocou replanejamentos inúteis e cancelamento, em vez de uma execução segura.

A correção foi adicionar um gate semântico antes de aceitar o plano. Ele verifica ferramentas registradas, allowlist da missão, argumentos obrigatórios e verificadores de sucesso registrados. Se o plano falha nesse gate, o Ultron usa o fallback determinístico existente e mantém a falha do modelo na telemetria; não executa a ferramenta inventada, não amplia o sandbox e não promove sucesso por texto. Os testes específicos passaram e o smoke foi repetido com sucesso, com **50 eventos** na missão.

## Verificações

| Gate operacional | Resultado |
|---|---:|
| Ruff nos arquivos alterados | PASS |
| Suíte completa | 197 passed, 1 warning preexistente de `TestClient`/`httpx` |
| Segurança Windows | 12 passed, 1 skipped |
| Smoke E2E com perfil padrão | PASS |
| Smoke E2E com `local-capable` + `gr1-gr2`, após gate semântico | PASS |
| Dry-run do probe | PASS |
| Probe público difícil 3B | Completo, 16 variantes |
| Probe público difícil 0,5B | Completo, 16 variantes |

## Como executar o perfil de desenvolvimento

```powershell
# Modelo local mais capaz e GR-1 + GR-2 opt-in
.\scripts\start.ps1 -ModelProfile local-capable -CognitionProfile gr1-gr2

# Probe público curto, resumível e development-only
.\.venv\Scripts\python.exe scripts\run_capability_probe.py `
  --model ollama_research `
  --seed 43 `
  --max-tasks 8 `
  --max-new-variants 4
```

O segundo comando pode ser repetido com `--resume <diretório-do-probe>` ou com o diretório de saída correspondente. Ele grava o checkpoint após cada variante e não considera uma coleta parcial como resultado científico final.

## Limites mantidos

A validation privada pós-emenda continua bloqueada e não foi reutilizada. O unseen continua fechado porque a geração truly private-only e a auditoria de isolamento ainda são pré-condições. Nenhuma destas medições públicas altera o modelo, a amostra, os seeds, os contratos ou o freeze do experimento confirmatório GR-1 versus GR-2.

O próximo investimento de maior alavancagem é melhorar o ciclo de recuperação e verificação com uma hipótese isolada, usando o probe público como filtro rápido e somente depois uma coleta privada nova e congelada. O Ultron pode ficar mais capaz em pouco tempo; afirmar AGI exigiria uma evidência muito mais ampla, robusta e independente do que o estado atual oferece.
