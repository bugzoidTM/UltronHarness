# Port Audit — Project Athena

## Proveniência e escopo

| Campo | Valor |
|---|---|
| `origin_repository` | `bugzoidTM/UltronLocal` |
| Licença declarada na auditoria anterior | Ausente |
| Forma de reaproveitamento | Algoritmos reimplementados, sem copiar o código-fonte |
| Destino | UltronPro local research architecture |
| Decisão operacional | Shadow/experimental até ablação e gates |

A análise foi estática. Nenhum arquivo externo foi executado, copiado ou importado. A ausência de licença continua a impedir reutilização literal e distribuição baseada no código externo.

## Matriz de decisão

| Módulo externo | Decisão | Algoritmo aproveitável | Exclusões obrigatórias | Destino Athena |
|---|---|---|---|---|
| `memory_governor.py` | **ADAPT** | Sinais de evidência, risco, falha, ferramenta e grounding para writeback | Heurística textual de preferência, estado JSONL | `ultron/memory/governor.py` e SQLite `memory_write_decisions` |
| `skill_memory.py` | **ADAPT** | Registro de contagem de uso/sucesso e exemplos | Arquivos paralelos de estado e dependências legadas | `ultron/learning/skills.py` sobre tabela canônica `skills` |
| `skill_memory_governor.py` | **ADAPT** | Health = sucesso × utilidade × confiança × recência; degradação preservando histórico | Remoção de diretórios/skills e recarga automática | `ultron/learning/skill_governor.py`, somente estados SQLite |
| `uncertainty.py` | **PORT/ADAPT** | Posterior Beta, intervalo aproximado e lower bound conservador | Nenhum acesso externo | `ultron/cognition/self_model.py` com SQLite |
| `self_model.py` | **ADAPT** | Agregação de outcomes por domínio/tipo/estratégia | Perfis subjetivos e JSON independente | capability estimates empíricos |
| `world_model.py` | **DEFER** | Observação e predição de ação | Qualquer influência imediata em plano/política | Sprint 2, shadow-only |
| `local_reasoning_engine.py` | **DEFER** | Roteamento simbólico de subtarefas | Uso de `eval()` | Sprint 2 com AST whitelist |
| `internal_critic.py` | **DEFER** | Separação entre evidência e coerência | Julgamento LLM quando há verificador | Sprint 2, evidence-first |
| `rl_policy.py` | **DEFER/SHADOW** | Posterior por estratégia | Controle de ação real | Sprint 3, observer-only |

## Testes e promoção

Os módulos ADAPT só podem ser promovidos após testes determinísticos, persistência canônica, uma ablação de benchmark e ausência de regressão em política, sandbox, kill switch e segurança Windows. A decisão inicial é **EXPERIMENTAL**; a seleção de experiência não deve modificar código, política, escopo de filesystem, rede ou credenciais.
