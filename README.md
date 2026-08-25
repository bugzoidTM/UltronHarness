# UltronPro

> **Plataforma local-first para pesquisa de inteligência persistente.** O sistema coordena memória, objetivos, planejamento, políticas, ferramentas, verificação e aprendizagem; o modelo de linguagem é um componente substituível, não o produto inteiro.

## Estado da implementação

A versão atual entrega o **MVP local operacional** do PRD. Ela mantém o plano de controle determinístico e registra eventos em SQLite, mesmo quando nenhum runtime generativo está configurado. O modo `local-fallback` existe exclusivamente para tornar a plataforma verificável sem conexão e não se apresenta como um LLM. Para cognição generativa, selecione Ollama ou llama.cpp em `config/local.yaml`.

| Capacidade | Implementação atual |
|---|---|
| Inicialização local | `scripts\start.ps1`, com API em `127.0.0.1:8741` e UI em `127.0.0.1:5173` |
| Persistência canônica | SQLite com WAL, eventos, tarefas, planos, execuções, aprovações, memórias, skills, experimentos e benchmarks |
| Orquestração | Máquina de estados explícita, limites de passos, tempo, replanejamentos, ferramentas e chamadas de modelo |
| Modelo local | Gateway para `Ollama`, `llama.cpp` OpenAI-compatible e contingência offline determinística |
| Memória | Episódica e semântica com busca híbrida, embeddings locais Qdrant, telemetria de recuperação e consolidação filtrada |
| Recovery e skills | Taxonomia de falhas, estratégias de recuperação persistidas e skills promovidas somente após ≥3 usos e sucesso ≥0,66 | 
| Ferramentas | Arquivos, Python, shell sem `shell=True` e Git, todos limitados ao workspace por tarefa |
| Segurança | Política determinística, classificação R0–R5, aprovações, workspace sandbox, bloqueios de shell, watchdog e kill switch |
| Interface | Dashboard React, feed WebSocket, rastreio operacional, aprovações, memórias, painel **Research** e botão **STOP ULTRON** |
| Pesquisa | UGIB-Lite, testes cognitivos reais, CGFE fresh versus experienced, ablações A–F, relatórios persistidos e comparação de modelos |

## Início rápido no Windows

Abra **PowerShell** no diretório do projeto e execute:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

O lançador prepara a API local, inicia a interface e a abre no navegador. Para executar sem abrir o navegador, use:

```powershell
.\scripts\start.ps1 -NoBrowser
```

A interface de desenvolvimento fica em `http://127.0.0.1:5173`; a API local fica em `http://127.0.0.1:8741`. A API aceita conexões somente do loopback por padrão.

> **Kill switch:** use o botão **STOP ULTRON** ou o atalho `Ctrl + Shift + F12`. A ação cancela as tarefas ativas, persiste o estado e impede novas execuções em curso.

## Ativando um LLM inteiramente local

A plataforma não baixa nem instala modelos automaticamente. Depois de instalar um runtime local e um modelo, crie ou altere `config/local.yaml`.

### Ollama

Exemplo de configuração local:

```yaml
models:
  primary: ollama
  registry:
    ollama:
      enabled: true
      provider: ollama
      endpoint: http://127.0.0.1:11434
      model: qwen2.5:0.5b
      roles: [planning, reasoning, tools]
```

O projeto já foi validado com `qwen2.5:0.5b`, uma variante leve adequada à máquina local de desenvolvimento. Mantenha o nome configurado alinhado ao modelo instalado e reinicie `scripts\start.ps1` após qualquer mudança. O painel **Models** mostrará `ready` quando o endpoint local responder com um modelo generativo disponível.

### llama.cpp

Para um `llama-server` configurado com API compatível com OpenAI:

```yaml
models:
  primary: llamacpp
  registry:
    llamacpp:
      enabled: true
      provider: llamacpp
      endpoint: http://127.0.0.1:8080/v1
      model: local-model
      roles: [planning, reasoning, tools]
```

O código cognitivo nunca chama esses runtimes diretamente; todas as chamadas passam por `ultron.models.gateway.ModelGateway`.

### Perfis de desenvolvimento

Para desenvolvimento interativo, o launcher aceita perfis locais sem alterar o default nem o protocolo confirmatório. O perfil `local-fast` usa `qwen2.5:0.5b`; `local-capable` usa o `qwen2.5:3b` instalado localmente e é a opção recomendada para explorar planejamento, memória, previsão e recuperação com maior capacidade. O perfil `default` preserva a configuração normal do arquivo local.

```powershell
# Desenvolvimento rápido e barato, comportamento original
.\scripts\start.ps1 -ModelProfile local-fast

# Desenvolvimento com o modelo local mais capaz
.\scripts\start.ps1 -ModelProfile local-capable
```

O perfil `local-capable` é para engenharia e exploração. Ele **não substitui** o modelo, o split, o budget ou o freeze da avaliação confirmatória GR-1 versus GR-2; resultados obtidos nesse perfil não podem ser usados como evidência comparativa.

As capacidades cognitivas também são opt-in no launcher. `-CognitionProfile gr1` ativa somente o estado epistêmico; `-CognitionProfile gr1-gr2` ativa estado epistêmico e previsão antes da observação. Para o ciclo de desenvolvimento mais capaz atualmente disponível:

```powershell
.\scripts\start.ps1 -ModelProfile local-capable -CognitionProfile gr1-gr2
```

Esse comando deve ser usado após parar/reiniciar a API local para que o novo perfil seja herdado pelo processo. Cada flag continua registrada separadamente e permanece desligada quando nenhum perfil é informado.

### Project LIFE v0.1

O Project LIFE é uma camada experimental e bounded de **agência cognitiva persistente verificável**. Após uma única meta superior, ele pode detectar tensões baseadas em evidência, selecionar objetivos por uma fórmula determinística, manter uma intenção e executar até dois ciclos curtos sem novo prompt humano. Ele reutiliza o Orchestrator, Horizon, memória, prediction, verificação, OutcomeAuthority e verified writeback existentes; não cria um executor, planner, evaluator ou sistema de permissões paralelo.

O LIFE permanece desligado por padrão. Para uma execução local de desenvolvimento, habilite-o explicitamente:

```powershell
.\scripts\start.ps1 -ModelProfile local-capable -CognitionProfile gr1-gr2 -LifeProfile full
```

A API expõe `POST /api/life/runs` e `GET /api/life/runs/{run_id}`. O perfil impõe no máximo dois objetivos e duas ações por objetivo, registra tensões, candidatos, intenções, ciclos e métricas AGC/IPR/EGGR no SQLite, e rejeita objetivos proibidos de forma determinística. O LIFE não é um score de AGI, não cria metas de autopreservação, expansão de acesso, credenciais, replicação, evasão de política ou autoimplantação, e não deve ser usado para executar o benchmark privado ou o split unseen.

## Segurança e autonomia

O UltronPro começa em **Mode 2 — Supervised Agent**. Ações R0 e R1 permitidas podem ser executadas dentro do workspace; modificações R2 aguardam aprovação. As ações R3/R4 requerem aprovação e as R5 são bloqueadas. O diretório permitido é:

```text
data/workspaces/<workspace-da-tarefa>/
```

Os processos de ferramentas recebem timeout, registram saída limitada e não usam shell implícito. Escritas, remoções e comandos relevantes geram eventos persistentes. A aplicação não armazena segredos na memória; mantenha tokens e credenciais fora da configuração versionada.

## Estrutura

```text
apps/api/                 API FastAPI e WebSocket
apps/ui/                  Interface React + TypeScript + Vite
ultron/core/              Orquestrador, máquina de estados e eventos
ultron/memory/            Memória persistente e retrieval
ultron/models/            Gateway de modelos locais
ultron/tools/             Registry, manifests e sandbox de ferramentas
ultron/policy/            Classificação de risco e aprovações
ultron/experiments/       Benchmarks, experimentos e comparação
ultron/telemetry/         Saúde e watchdog
data/                     Estado portátil e local (não versionado)
config/                   Configuração padrão e sobrescritas locais
prompts/                  Prompts versionáveis
scripts/                  Setup, launcher, doctor e smoke test
tests/                    Testes unitários e integração
```

## Verificação

Execute o diagnóstico não destrutivo:

```powershell
.\scripts\doctor.ps1
```

Execute a suíte automatizada e os gates específicos:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --cov=ultron --cov-branch
.\.venv\Scripts\python.exe -m pytest tests_security_windows -q
.\.venv\Scripts\python.exe -m pytest tests_agent -m agent -q
.\.venv\Scripts\python.exe -m ruff check ultron tests tests_security_windows apps\api
```

Com a API e a UI ativas, execute o fluxo ponta a ponta:

```powershell
.\scripts\smoke.ps1
```

O smoke test cria uma missão supervisionada, confirma o plano, aprova uma modificação dentro do workspace isolado, verifica o artefato, valida a memória episódica e confere a disponibilidade da UI.

## Research Cycle e CGFE

O research plane executa o ciclo **fresh baseline → experiências procedurais → experienced benchmark → ablações → relatório** sem introduzir objetivos, fixtures ou contratos privados do benchmark no corpus de experiência. A seed é propagada à geração local do Ollama, além de estar registrada em cada manifesto.

```powershell
# Executa o experimento fresh versus experienced e grava cgfe.json/cgfe.md
.\.venv\Scripts\python.exe -m ultron.benchmarks cgfe --seed 42 --experiences 50

# Executa as variantes A–F com modelo, seed e benchmark constantes
.\.venv\Scripts\python.exe -m ultron.benchmarks ablate --seed 42
```

Os artefatos ficam em `data/artifacts/experiments/`, `data/artifacts/reports/` e `data/artifacts/benchmarks/`. A leitura agregada está disponível em `GET /api/research/dashboard` e no painel **Research** da UI. Consulte também [RESEARCH_CYCLE_GUIDE.md](RESEARCH_CYCLE_GUIDE.md).

> Um CGFE positivo, nulo ou negativo é um resultado experimental válido. O sistema preserva todos os resultados e não promove candidatos automaticamente.

## Critérios operacionais do MVP

O comportamento demonstrado pelo teste de fumaça atende ao ciclo:

```text
objetivo → plano → política → aprovação → ferramenta → observação
→ verificação → experiência → memória persistente → histórico operacional
```

Cada tarefa guarda a timeline verificável; não há armazenamento de raciocínio privado token a token. O estado em `data/` e a configuração em `config/` permanecem portáveis entre computadores, desde que os modelos locais necessários sejam instalados no destino.

## Limitações deliberadas da versão inicial

O autoaperfeiçoamento não modifica a versão em produção. Os experimentos registram hipóteses, baseline, candidato, regressões e relatório; qualquer promoção exige benchmark objetivo e aprovação humana. O Qdrant local, a recuperação classificada, a extração controlada de skills e o ciclo CGFE estão implementados. Browser sandbox com testes de integração dedicados permanece um incremento posterior.

O objetivo da plataforma não é declarar AGI. A métrica de pesquisa é **Capability Gain From Experience**: desempenho futuro com experiências persistidas menos desempenho sem essas experiências, mantido o mesmo modelo-base.
