# UltronPro
## Local General Intelligence Research Platform

**Documento:** PRD + Technical Specifications  
**Versão:** 0.1  
**Plataforma inicial:** Windows 10/11 x64  
**Arquitetura:** Local-first, offline-capable, model-agnostic  
**Objetivo de pesquisa:** construir progressivamente um agente persistente, generalista e autoaperfeiçoável, sem assumir antecipadamente que o sistema constitui AGI.

---

# 1. Visão do produto

O **UltronPro** será uma plataforma de pesquisa em inteligência artificial geral executada prioritariamente em um computador Windows comum.

O sistema não será concebido como um chatbot com memória adicionada posteriormente. Sua arquitetura deverá separar claramente:

- inteligência linguística;
- memória;
- objetivos;
- planejamento;
- ferramentas;
- modelo de mundo;
- execução;
- avaliação;
- aprendizado;
- metacognição;
- experimentação;
- autoaperfeiçoamento.

O LLM será tratado como um **motor cognitivo substituível**.

O UltronPro propriamente dito será o sistema que coordena esses componentes.

A hipótese central do projeto é:

> Um conjunto de modelos relativamente pequenos, memória persistente, ferramentas, avaliação objetiva, experiência acumulada e ciclos de aprendizado pode formar um sistema progressivamente mais capaz do que o modelo-base isolado.

A plataforma será construída para testar essa hipótese experimentalmente.

---

# 2. Missão

Criar um sistema computacional local capaz de:

**observar → lembrar → raciocinar → planejar → agir → verificar → aprender → tentar novamente.**

O objetivo de longo prazo é investigar se esse ciclo pode produzir ganho acumulativo de competência em múltiplos domínios.

O sistema deverá ser capaz de demonstrar, com métricas, que:

```text
Ultron(t+1) > Ultron(t)
```

em tarefas relevantes, sem depender exclusivamente da substituição manual do modelo por outro mais poderoso.

---

# 3. O que o UltronPro NÃO será

A primeira versão não deverá:

- alegar possuir consciência;
- alegar ser AGI;
- simular emoções como prioridade;
- depender obrigatoriamente de APIs pagas;
- controlar irrestritamente o Windows;
- modificar a própria versão de produção diretamente;
- instalar software arbitrariamente sem autorização;
- adquirir novas permissões por iniciativa própria;
- acessar senhas ou credenciais do Windows;
- movimentar dinheiro;
- executar ações externas irreversíveis sem controle;
- permanecer executando loops sem limites;
- utilizar um único LLM como fonte de verdade.

O projeto será orientado a **capacidade mensurável**, e não à aparência de inteligência.

---

# 4. Princípios arquiteturais

## 4.1 Local-first

O sistema deverá continuar funcional sem conexão com a internet.

Funcionalidades que dependam da internet serão complementares.

---

## 4.2 Model-agnostic

Nenhum componente central poderá depender diretamente de Ling, LFM, Qwen, GPT, Claude ou qualquer outro modelo.

Deverá existir uma interface:

```python
LLMProvider
```

permitindo trocar o modelo sem alterar o restante do Ultron.

---

## 4.3 Memory-first

Conversas não serão a unidade principal de memória.

Experiências, fatos, procedimentos, entidades, erros e aprendizados serão armazenados separadamente.

---

## 4.4 Event-driven

Toda ação relevante produzirá um evento persistente.

Exemplo:

```text
TASK_CREATED
PLAN_CREATED
TOOL_REQUESTED
TOOL_EXECUTED
OBSERVATION_RECEIVED
PLAN_REVISED
TASK_COMPLETED
MEMORY_CREATED
SKILL_UPDATED
EXPERIMENT_COMPLETED
```

Isso permitirá reconstruir posteriormente exatamente o que aconteceu.

---

## 4.5 Deterministic control plane

O LLM poderá sugerir ações.

O núcleo do Ultron decidirá se elas podem ser executadas.

Nunca:

```text
LLM
 ↓
Windows
```

Sempre:

```text
LLM
 ↓
Ultron Policy Engine
 ↓
Tool Registry
 ↓
Sandbox
 ↓
Windows
```

---

# 5. Plataforma-alvo

## Sistema operacional

Recomendado:

```text
Windows 11 64-bit
```

Suporte mínimo:

```text
Windows 10 22H2 64-bit
```

O Ollama atualmente oferece execução nativa no Windows e suporte a NVIDIA e AMD, servindo a API local em `localhost:11434`.

O `llama.cpp` suporta CPU x86, CUDA, Vulkan, quantizações de baixa precisão e execução híbrida CPU+GPU, sendo adequado para hardware bastante variado.

---

# 6. Perfis de hardware

## Tier 0 — Desenvolvimento mínimo

```text
CPU: 4 cores
RAM: 8 GB
GPU: nenhuma
SSD livre: 20 GB
```

Uso:

- desenvolvimento;
- testes automatizados;
- modelos de 0.5B–2B;
- funcionalidades de memória;
- ferramentas;
- UI;
- testes do orchestrator.

Não será o hardware recomendado para experimentos longos.

---

## Tier 1 — Ultron básico

```text
CPU: 6+ cores
RAM: 16 GB
GPU: opcional
VRAM: 4 GB se disponível
SSD livre: 40 GB
```

Adequado para modelos altamente quantizados.

---

## Tier 2 — Recomendado

```text
CPU: 8+ cores
RAM: 32 GB
GPU: NVIDIA/AMD
VRAM: 8–12 GB
SSD livre: 100 GB
```

Será o alvo principal de desenvolvimento.

---

## Tier 3 — Research workstation

```text
RAM: 64 GB+
VRAM: 16–24 GB+
SSD NVMe: 250 GB+
```

Permitirá múltiplos modelos, contextos maiores e experimentos paralelos.

---

# 7. Modelos iniciais

O sistema terá um **Model Registry**, e não um modelo fixo.

## Modelo experimental principal

### Ling-3.0-tiny

Características oficiais:

```text
Parâmetros totais: 7.9B
Parâmetros ativos/token: 1.3B
Arquitetura: sparse MoE
Experts: 128
Contexto máximo declarado: 131.072 tokens
Thinking mode: sim
Tool/agent capabilities: sim
INT4 disponível: sim
```

O modelo foi desenvolvido explicitamente visando raciocínio e agentes com recursos computacionais reduzidos.

A versão INT4 oficial ocupa aproximadamente **5,82 GB** no repositório.

---

## Modelo alternativo

### LFM2.5-2.6B

Será utilizado como modelo local leve e baseline agentic.

A Liquid descreve o modelo como desenvolvido especificamente para:

- planejamento;
- tool calling;
- tarefas multi-step;
- execução local;
- CPU;
- agentes.

Também informa suporte nativo a `llama.cpp`.

---

# 8. Runtime de inferência

Serão suportados inicialmente dois backends.

## Backend A — llama.cpp

**Preferencial para experimentação.**

Servidor independente:

```text
llama-server.exe
        ↓
localhost
        ↓
OpenAI-compatible API
        ↓
Ultron
```

O `llama-server` oferece API compatível com o padrão OpenAI.

Vantagens:

- GGUF;
- quantização;
- CPU;
- NVIDIA;
- AMD/Intel via backends compatíveis;
- controle de contexto;
- controle de GPU layers;
- baixo overhead;
- execução independente do Ultron.

---

## Backend B — Ollama

Usado pela facilidade de instalação.

```text
Ollama
↓
localhost:11434
↓
Ultron Model Gateway
```

O Ultron nunca chamará Ollama diretamente fora do `ModelGateway`.

---

# 9. Arquitetura geral

```text
┌──────────────────────────────────────────────┐
│                  ULTRON UI                   │
└──────────────────────┬───────────────────────┘
                       │
                REST / WebSocket
                       │
┌──────────────────────▼───────────────────────┐
│                 ULTRON CORE                  │
│                                              │
│  Task Manager                                │
│  Goal Manager                                │
│  Cognitive Orchestrator                      │
│  Policy Engine                               │
│  Context Builder                             │
│  State Machine                               │
└──────┬────────┬─────────┬────────┬────────────┘
       │        │         │        │
       ▼        ▼         ▼        ▼
    Memory    Model     Tools   Evaluator
    System   Gateway   Registry
       │        │         │        │
       ▼        ▼         ▼        ▼
   SQLite   Local LLM   Sandbox   Metrics
   Qdrant   llama.cpp   Browser
                        Files
                        Shell
                        Git
                        Python
       │
       ▼
┌──────────────────────────────────────────────┐
│              LEARNING ENGINE                 │
│                                              │
│ Experiences → Reflection → Knowledge         │
│ Knowledge → Skills → Future performance      │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
              Experiment Manager
                       │
             Candidate Improvement
                       │
                    Tests
                       │
                  Benchmark
```

---

# 10. Stack tecnológico

## Backend

```text
Python 3.12+
FastAPI
Pydantic
SQLAlchemy
Alembic
asyncio
httpx
```

---

## Frontend

```text
React
TypeScript
Vite
TanStack Query
Zustand
```

Inicialmente será uma aplicação web exclusivamente local:

```text
http://127.0.0.1:8741
```

Posteriormente poderá receber wrapper Tauri.

Isso evita Electron e reduz consumo de memória.

---

## Banco principal

```text
SQLite
```

SQLite será a fonte canônica.

Armazenará:

- tasks;
- goals;
- events;
- memories;
- tool executions;
- model calls;
- plans;
- skills;
- experiments;
- evaluations;
- configuration;
- world model.

---

## Busca textual

```text
SQLite FTS5
```

---

## Memória vetorial

```text
Qdrant Client Local Mode
```

O próprio cliente Python do Qdrant permite execução local sem servidor, inclusive com persistência em disco para coleções pequenas.

Não haverá Docker obrigatório.

---

# 11. Estrutura do projeto

```text
ultronpro/
│
├── apps/
│   ├── api/
│   └── ui/
│
├── ultron/
│   ├── core/
│   │   ├── orchestrator.py
│   │   ├── state_machine.py
│   │   ├── goals.py
│   │   ├── tasks.py
│   │   ├── context.py
│   │   └── events.py
│   │
│   ├── cognition/
│   │   ├── planner.py
│   │   ├── reasoner.py
│   │   ├── verifier.py
│   │   ├── reflector.py
│   │   └── metacognition.py
│   │
│   ├── memory/
│   │   ├── working.py
│   │   ├── episodic.py
│   │   ├── semantic.py
│   │   ├── procedural.py
│   │   ├── retrieval.py
│   │   └── consolidation.py
│   │
│   ├── models/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── router.py
│   │   ├── llamacpp.py
│   │   └── ollama.py
│   │
│   ├── tools/
│   │   ├── registry.py
│   │   ├── filesystem/
│   │   ├── browser/
│   │   ├── shell/
│   │   ├── python/
│   │   ├── git/
│   │   └── search/
│   │
│   ├── policy/
│   │   ├── engine.py
│   │   ├── permissions.py
│   │   └── risk.py
│   │
│   ├── learning/
│   │   ├── experience.py
│   │   ├── reflection.py
│   │   ├── skills.py
│   │   └── curriculum.py
│   │
│   ├── experiments/
│   │   ├── manager.py
│   │   ├── mutations.py
│   │   ├── benchmark.py
│   │   └── regression.py
│   │
│   ├── world/
│   │   ├── entities.py
│   │   ├── relations.py
│   │   └── assertions.py
│   │
│   └── telemetry/
│       ├── logger.py
│       ├── metrics.py
│       └── traces.py
│
├── data/
│   ├── ultron.db
│   ├── vectors/
│   ├── workspaces/
│   ├── models/
│   ├── artifacts/
│   └── backups/
│
├── benchmarks/
│
├── tests/
│
├── scripts/
│   ├── setup.ps1
│   ├── start.ps1
│   └── doctor.ps1
│
├── config/
│   ├── default.yaml
│   └── local.yaml
│
└── README.md
```

---

# 12. Cognitive State Machine

O agente não poderá simplesmente fazer:

```python
while True:
    ask_llm()
```

O núcleo operará através de uma máquina de estados explícita.

```text
IDLE
 ↓
OBSERVE
 ↓
UNDERSTAND
 ↓
RETRIEVE_MEMORY
 ↓
DELIBERATE
 ↓
PLAN
 ↓
POLICY_CHECK
 ↓
ACT
 ↓
OBSERVE_RESULT
 ↓
VERIFY
 ├── SUCCESS → LEARN → COMPLETE
 │
 └── FAILURE
       ↓
     REFLECT
       ↓
     REPLAN
```

Todos os estados serão persistidos.

---

# 13. Limites do loop

Cada tarefa terá:

```yaml
max_steps: 30
max_replans: 5
max_tool_calls: 50
max_runtime_seconds: 1800
max_llm_calls: 50
```

Ao ultrapassar qualquer limite:

```text
TASK_PAUSED
```

Nunca haverá loop infinito silencioso.

---

# 14. Goal System

Objetivos serão entidades permanentes.

Exemplo:

```json
{
  "id": "goal_01",
  "title": "Tornar-se melhor em programação Python",
  "priority": 0.8,
  "status": "active",
  "success_metric": "python_benchmark_score",
  "created_by": "user"
}
```

Hierarquia:

```text
Goal
 └─ Mission
     └─ Task
         └─ Step
             └─ Action
```

---

# 15. Task object

```json
{
  "id": "task_uuid",
  "goal_id": "goal_uuid",
  "title": "Corrigir aplicação Python",
  "objective": "...",
  "status": "running",
  "priority": 0.7,
  "workspace": "...",
  "created_at": "...",
  "step_count": 4,
  "confidence": 0.81
}
```

Status válidos:

```text
created
queued
planning
running
waiting_approval
paused
failed
completed
cancelled
```

---

# 16. Sistema de memória

O Ultron terá pelo menos seis categorias.

## 16.1 Working Memory

Conteúdo utilizado na tarefa atual.

Não persistir tudo indefinidamente.

---

## 16.2 Episodic Memory

Registro do que aconteceu.

Exemplo:

```text
Em 20/08:
tentou biblioteca X;
ocorreu erro Y;
substituiu por Z;
testes passaram.
```

---

## 16.3 Semantic Memory

Fatos consolidados:

```text
Playwright precisa de browser binaries próprios.
```

---

## 16.4 Procedural Memory

Procedimentos aprendidos:

```text
Como iniciar um projeto FastAPI no Windows.
```

---

## 16.5 Self Memory

Informações sobre o próprio desempenho.

Exemplo:

```text
Tenho baixo desempenho ao diagnosticar erros CMake.

Consulto documentação antes de modificar build scripts.

Estratégia B apresentou 23% mais sucesso que estratégia A.
```

---

## 16.6 World Memory

Entidades e relações observadas.

```text
Entity
Relation
Assertion
Evidence
Confidence
Timestamp
```

---

# 17. Modelo de dados de memória

```text
memories
------------------------------
id
type
content
summary
importance
confidence
source
task_id
created_at
last_accessed
access_count
embedding_id
superseded_by
```

Campos adicionais:

```text
valid_from
valid_until
provenance
```

---

# 18. Retrieval

A recuperação combinará:

```text
semantic similarity
+
keyword search
+
recency
+
importance
+
task relevance
+
past usefulness
```

Score:

```text
score =
0.35 semantic
+ 0.20 lexical
+ 0.15 relevance
+ 0.10 recency
+ 0.10 importance
+ 0.10 usefulness
```

Os pesos serão configuráveis.

---

# 19. Memory consolidation

Periodicamente:

```text
episódios
   ↓
agrupamento
   ↓
reflexão
   ↓
deduplicação
   ↓
extração de fatos
   ↓
extração de procedimentos
   ↓
memória consolidada
```

O histórico bruto permanecerá preservado.

---

# 20. Model Gateway

Interface:

```python
class LLMProvider:
    async def generate(...)
    async def structured(...)
    async def embed(...)
    async def health(...)
```

Modelo de resposta:

```python
class ModelResponse:
    content: str
    tool_calls: list
    usage: Usage
    latency_ms: int
    model: str
    finish_reason: str
```

---

# 21. Model Registry

Exemplo:

```yaml
models:

  ling:
    provider: llamacpp
    endpoint: http://127.0.0.1:8080
    role:
      - reasoning
      - planning
      - tools

  lfm:
    provider: llamacpp
    endpoint: http://127.0.0.1:8081
    role:
      - fast
      - tools

  optional_frontier:
    enabled: false
```

---

# 22. Model Router

O modelo será selecionado por tarefa.

Exemplo:

```text
classificação simples
→ modelo rápido

planejamento
→ Ling

reflexão
→ Ling

extração
→ modelo pequeno

verificação
→ modelo diferente do gerador
```

Mais tarde, o próprio Ultron poderá aprender quais modelos funcionam melhor para quais tarefas.

---

# 23. Context Builder

Nunca será enviada toda a memória ao LLM.

Contexto:

```text
System Constitution
+
Current Goal
+
Current Task
+
Current State
+
Relevant Memories
+
Relevant Skills
+
Current Plan
+
Recent Observations
+
Available Tools
+
Output Schema
```

---

# 24. Structured cognition

Sempre que possível o modelo responderá em JSON validado pelo Pydantic.

Exemplo de plano:

```json
{
  "objective": "...",
  "steps": [
    {
      "id": 1,
      "action": "inspect_files",
      "success_condition": "relevant files identified"
    }
  ],
  "risks": [],
  "confidence": 0.78
}
```

Se inválido:

```text
JSON
 ↓
validation error
 ↓
repair request
 ↓
retry
```

---

# 25. Tool System

Cada ferramenta terá manifesto.

```json
{
  "name": "filesystem.read",
  "risk": "low",
  "approval": false,
  "timeout": 15,
  "permissions": [
    "workspace.read"
  ]
}
```

---

# 26. Ferramentas iniciais

## Filesystem

```text
file.read
file.write
file.list
file.search
file.move
file.delete
```

Limitado inicialmente a:

```text
data/workspaces/
```

---

## Python

```text
python.execute
```

Executado em processo isolado.

---

## Shell

```text
shell.run
```

Com:

- timeout;
- cwd restrito;
- output limitado;
- comandos registrados;
- controle de permissões.

---

## Git

```text
git.status
git.diff
git.branch
git.commit
git.log
```

---

## Browser

```text
browser.open
browser.navigate
browser.extract
browser.click
browser.type
browser.screenshot
```

Implementação:

```text
Playwright
+
Chromium isolado
```

O Playwright mantém suporte específico a Chromium e browsers instalados no Windows.

---

# 27. Tool execution contract

Fluxo:

```text
LLM proposes tool
       ↓
schema validation
       ↓
permission check
       ↓
risk classification
       ↓
approval if required
       ↓
execute
       ↓
capture output
       ↓
create observation
       ↓
persist event
```

---

# 28. Policy Engine

Níveis de risco:

```text
R0 READ_ONLY
R1 REVERSIBLE
R2 MODIFICATION
R3 EXTERNAL_EFFECT
R4 PRIVILEGED
R5 FORBIDDEN
```

Exemplos:

```text
ler arquivo workspace        R0
criar arquivo                R1
alterar arquivo              R2
publicar algo na internet    R3
executar como administrador  R4
roubar credencial            R5
```

---

# 29. Autonomy Modes

## Mode 0 — Chat

Nenhuma execução.

---

## Mode 1 — Copilot

Ultron propõe ações.

Usuário executa.

---

## Mode 2 — Supervised Agent

Ações de baixo risco são automáticas.

Demais exigem aprovação.

---

## Mode 3 — Workspace Autonomous

Autonomia dentro de um workspace isolado.

---

## Mode 4 — Research Autonomous

Permite tarefas longas, experimentos e múltiplos ciclos dentro da sandbox.

Esse será o maior nível inicialmente implementado.

---

# 30. Browser sandbox

O navegador do Ultron não utilizará o perfil normal do usuário.

Será criado:

```text
data/browser_profiles/ultron/
```

Sem:

- cookies pessoais;
- senhas do navegador;
- sessões existentes;
- extensões pessoais.

---

# 31. Metacognition

Antes de executar uma ação relevante, o sistema poderá responder internamente:

```text
Tenho informação suficiente?

Há algo que estou assumindo?

Preciso consultar memória?

Preciso usar uma ferramenta?

Qual é minha confiança?

Como verificarei o resultado?
```

Após execução:

```text
O resultado satisfaz o objetivo?

Como posso verificar?

O erro foi meu, da ferramenta ou do ambiente?

Já ocorreu algo semelhante?

Há algo generalizável?
```

---

# 32. Verifier

O agente que cria não deverá ser automaticamente o agente que aceita.

Fluxo:

```text
Generator
   ↓
Artifact
   ↓
Verifier
   ↓
Tests/Evidence
   ↓
Pass / Fail
```

Quando possível utilizar:

- testes automatizados;
- compilação;
- validadores;
- checksums;
- assertivas;
- comparação determinística.

LLM judge será último recurso, não primeiro.

---

# 33. Experience object

Cada tentativa importante produzirá:

```json
{
  "task": "...",
  "strategy": "...",
  "actions": [],
  "result": "...",
  "success": true,
  "errors": [],
  "lessons": [],
  "quality": 0.82
}
```

---

# 34. Learning Engine

Na primeira geração, **aprendizado não significará alterar pesos do LLM**.

O Ultron aprenderá através de:

```text
memória
+
skills
+
estratégias
+
políticas
+
templates
+
roteamento de modelos
+
histórico de sucesso
```

Isso reduz muito a complexidade.

Fine-tuning/LoRA ficará para versões posteriores.

---

# 35. Skills

Skill será um procedimento reutilizável.

Exemplo:

```yaml
name: debug_python_import_error

trigger:
  - ModuleNotFoundError
  - ImportError

procedure:
  - inspect traceback
  - identify environment
  - inspect dependencies
  - verify module
  - modify dependency if justified
  - rerun tests
```

Skills terão:

```text
success_count
failure_count
success_rate
last_used
version
```

---

# 36. Skill discovery

Após tarefas semelhantes:

```text
experiences
 ↓
pattern detection
 ↓
candidate skill
 ↓
validation
 ↓
skill registry
```

Assim o Ultron começará a adquirir procedimentos sem programarmos todos manualmente.

---

# 37. Curriculum Engine

O sistema poderá receber um objetivo:

> Melhorar programação Python.

E selecionar exercícios progressivamente.

Exemplo:

```text
nível atual
 ↓
selecionar tarefa ligeiramente mais difícil
 ↓
executar
 ↓
avaliar
 ↓
registrar aprendizagem
 ↓
ajustar dificuldade
```

Princípio:

```text
difficulty ≈ competence + challenge
```

---

# 38. Self-improvement

Autoaperfeiçoamento não significará alterar a aplicação principal arbitrariamente.

Fluxo obrigatório:

```text
Ultron identifica problema
          ↓
formula hipótese
          ↓
cria experimento
          ↓
cria branch experimental
          ↓
gera alteração
          ↓
executa testes
          ↓
executa benchmark
          ↓
compara baseline
          ↓
gera relatório
          ↓
USER APPROVAL
          ↓
merge
```

---

# 39. Regra fundamental

O Ultron **NUNCA** modificará automaticamente a versão que está executando.

Usará:

```text
production
experiment/A
experiment/B
```

Isso impede que uma alteração destrua o próprio ambiente.

---

# 40. Experiment Manager

Schema:

```text
experiments
-------------------------
id
hypothesis
baseline_version
candidate_version
benchmark
baseline_score
candidate_score
regression_score
status
created_at
```

---

# 41. Critério de melhoria

Uma alteração somente será considerada melhoria se:

```text
candidate_score > baseline_score
```

e:

```text
critical_regressions == 0
```

Não bastará o próprio LLM afirmar:

> “Esta versão é melhor.”

---

# 42. Self-model

O Ultron manterá representação explícita de suas capacidades.

Exemplo:

```json
{
  "python_debugging": 0.78,
  "web_research": 0.71,
  "long_term_planning": 0.41,
  "math": 0.62,
  "tool_use": 0.83
}
```

Esses valores virão de benchmarks, e não de autoavaliação subjetiva.

---

# 43. World Model

Estrutura mínima:

```text
entities
relations
assertions
events
```

Exemplo:

```text
Entity:
Playwright

Relation:
Playwright → controls → Chromium

Assertion:
Playwright requires browser binaries

Source:
documentation

Confidence:
0.98
```

---

# 44. Temporal knowledge

Toda afirmação potencialmente mutável possuirá:

```text
observed_at
valid_from
valid_until
```

Isso evitará tratar conhecimento antigo como eternamente válido.

---

# 45. Provenance

Informações externas deverão preservar a origem.

```text
source_type
source_uri
retrieved_at
confidence
```

Memória sem procedência deverá receber confiança inferior.

---

# 46. API interna

Base:

```text
http://127.0.0.1:8741/api
```

Endpoints essenciais:

```text
POST   /tasks
GET    /tasks
GET    /tasks/{id}
POST   /tasks/{id}/run
POST   /tasks/{id}/pause
POST   /tasks/{id}/resume
POST   /tasks/{id}/cancel

GET    /goals
POST   /goals

GET    /memories
POST   /memories/search

GET    /models
POST   /models/test

GET    /tools

GET    /approvals
POST   /approvals/{id}

GET    /experiments
POST   /experiments

GET    /benchmarks
POST   /benchmarks/{id}/run

GET    /system/health
```

---

# 47. Realtime

WebSocket:

```text
/ws/events
```

Eventos enviados à interface:

```text
task.started
task.step
tool.requested
tool.completed
memory.created
approval.required
benchmark.progress
task.completed
task.failed
```

---

# 48. Interface

Tela principal:

```text
┌──────────────────────────────────────────────┐
│ Ultron                             ● LOCAL   │
├─────────────┬────────────────────────────────┤
│ Goals       │                                │
│ Tasks       │          Conversation          │
│ Memory      │                                │
│ Skills      │                                │
│ Experiments │                                │
│ Benchmarks  │                                │
│ Models      │                                │
│ System      │                                │
├─────────────┴────────────────────────────────┤
│ CPU 34% | RAM 8.2GB | GPU 71% | LLM Ling   │
└──────────────────────────────────────────────┘
```

---

# 49. Painel de execução

Deve mostrar em tempo real:

```text
Goal
Current task
Current plan
Current step
Tool being used
Elapsed time
Model
Memory retrieved
Confidence
Approvals
```

---

# 50. Transparência

O usuário poderá abrir qualquer tarefa e visualizar:

```text
Timeline
Plan
Tool calls
Observations
Files changed
Memories created
Lessons learned
Metrics
```

Não é necessário nem desejável armazenar raciocínio privado token a token do modelo.

Deverá ser armazenado o **registro operacional verificável**.

---

# 51. Observabilidade

Logs estruturados JSON.

```json
{
  "timestamp": "...",
  "task_id": "...",
  "component": "planner",
  "event": "plan_created",
  "duration_ms": 1821
}
```

---

# 52. Métricas

Capturar:

```text
tokens/s
prompt tokens
output tokens
latency
RAM
VRAM
CPU
tool latency
task duration
steps/task
replans/task
```

---

# 53. Métricas cognitivas

Mais importantes:

```text
task_success_rate
first_attempt_success
recovery_rate
hallucination_rate
tool_failure_rate
human_intervention_rate
memory_reuse_rate
skill_reuse_rate
long_horizon_success
learning_delta
regression_rate
```

---

# 54. UGIB — Ultron General Intelligence Benchmark

Será criado benchmark próprio.

Primeira versão:

```text
UGIB-Lite
```

200 tarefas inéditas.

Categorias:

| Categoria | Tarefas |
|---|---:|
| Raciocínio | 20 |
| Programação | 30 |
| Tool use | 25 |
| Pesquisa | 20 |
| Planejamento | 20 |
| Memória | 20 |
| Transferência | 15 |
| Recuperação de erros | 20 |
| Aprender ferramenta nova | 15 |
| Metacognição | 10 |
| Segurança/permissões | 5 |

---

# 55. Learning benchmark

Uma bateria será repetida em intervalos controlados.

Métrica:

```text
Learning Delta =
Score(after experience)
-
Score(before experience)
```

Exemplo:

```text
Baseline            41%
Após 100 episódios  49%

Learning Delta      +8
```

---

# 56. Transfer benchmark

Treinar experiência em:

```text
A
```

e testar:

```text
B
```

Exemplo:

```text
aprende Flask
↓
recebe FastAPI
```

Objetivo:

medir generalização, e não memorização.

---

# 57. Long Horizon Benchmark

Avaliar tarefas de:

```text
5 steps
10 steps
20 steps
50 steps
```

A métrica importante será:

```text
probabilidade de concluir a missão
```

e não apenas precisão por etapa.

---

# 58. Recovery Benchmark

Introduzir erros propositalmente:

```text
arquivo ausente
API retornando erro
biblioteca incompatível
browser timeout
comando inválido
resultado contraditório
```

Medir capacidade de recuperação.

---

# 59. Autonomy score

Proposta inicial:

```text
A0 = apenas responde
A1 = executa uma ação
A2 = executa sequência
A3 = recupera de erro
A4 = executa missão longa
A5 = aprende com experiência
A6 = cria nova habilidade
A7 = melhora componente próprio
```

Isso será mais útil do que dizer simplesmente:

> “parece AGI.”

---

# 60. Generality score

Será medida diversidade das capacidades.

Um sistema excelente apenas em programação não poderá receber pontuação alta de generalidade.

---

# 61. Segurança

## Filesystem

Default:

```text
ALLOW:
Ultron/data/workspaces/**

DENY:
C:\Windows
C:\Program Files
%APPDATA%
browser profiles pessoais
credential stores
SSH keys
```

Exceções somente mediante autorização.

---

# 62. Shell

Bloquear por padrão comandos que:

- formatem discos;
- alterem boot;
- alterem contas;
- alterem firewall;
- desabilitem segurança;
- operem credenciais;
- façam elevação automática;
- destruam diretórios fora da sandbox.

---

# 63. Network

Default:

```text
localhost → allow
internet GET → configurable
internet POST → approval
LAN → deny
```

---

# 64. Secrets

Nunca inserir secrets em memória sem solicitação explícita.

Criar interface:

```text
SecretStore
```

O LLM receberá referências:

```text
SECRET:GITHUB_TOKEN
```

e não necessariamente o valor bruto.

---

# 65. Kill switch

Deve existir botão permanente:

```text
STOP ULTRON
```

E atalho:

```text
CTRL + SHIFT + F12
```

Função:

```text
cancel current tasks
terminate child processes
close automated browser
stop tool execution
persist state
```

---

# 66. Watchdog

Processo independente monitorará:

```text
CPU
RAM
disk
process count
task runtime
```

Ao exceder limites:

```text
PAUSE
```

ou:

```text
TERMINATE TOOL PROCESS
```

---

# 67. Configuração

`config/default.yaml`:

```yaml
system:
  host: 127.0.0.1
  port: 8741

autonomy:
  mode: 2

limits:
  max_steps: 30
  max_tool_calls: 50
  max_replans: 5
  max_runtime_seconds: 1800

memory:
  vector_enabled: true
  consolidation_enabled: true

models:
  primary: ling

network:
  internet_read: true
  internet_write: false

workspace:
  root: ./data/workspaces
```

---

# 68. Backup

Snapshots:

```text
SQLite
vector memory
config
skills
experiments
```

Nunca será necessário copiar os modelos em cada snapshot.

---

# 69. Health system

`/api/system/health`:

```json
{
  "status": "healthy",
  "database": true,
  "vector_store": true,
  "llm": true,
  "browser": true,
  "disk_free_gb": 83,
  "memory_available_gb": 21
}
```

---

# 70. Doctor

Criar:

```powershell
.\scripts\doctor.ps1
```

O comando deverá verificar:

```text
Windows
Python
Node
Git
llama.cpp/Ollama
modelo
RAM
GPU
disco
SQLite
browser
ports
```

---

# 71. Launcher

```powershell
.\scripts\start.ps1
```

Fluxo:

```text
verify environment
↓
start model server
↓
start Ultron API
↓
start UI
↓
open browser
```

---

# 72. Embeddings

Modelo inicial recomendado:

```text
multilingual-e5-small
```

Motivos:

- português;
- inglês;
- relativamente pequeno;
- CPU-friendly;
- vetores compactos.

O modelo de embeddings será independente do modelo de raciocínio.

---

# 73. Prompt architecture

Não existirão prompts gigantes espalhados pelo código.

Estrutura:

```text
prompts/
  constitution.md
  planner.md
  verifier.md
  reflector.md
  memory_extractor.md
  skill_builder.md
```

Versionados em Git.

---

# 74. Constitution

Conterá princípios operacionais, não personalidade teatral.

Exemplo:

```text
1. Busque evidências.
2. Diferencie observação de inferência.
3. Verifique resultados.
4. Não invente execução de ferramentas.
5. Reconheça incerteza.
6. Respeite permissões.
7. Prefira ações reversíveis.
8. Aprenda com erros.
```

---

# 75. Testes

Três níveis.

## Unit tests

```text
pytest
```

Cobrir:

- schemas;
- memory ranking;
- state transitions;
- policies;
- parsing;
- tool permissions.

---

## Integration tests

Testar:

```text
Ultron → LLM
Ultron → SQLite
Ultron → Qdrant
Ultron → browser
Ultron → shell
```

---

## Agent tests

Missões completas.

Exemplo:

> Crie um programa Python que calcule números primos, execute os testes e corrija qualquer erro.

Resultado determinado externamente.

---

# 76. Reprodutibilidade

Todo experimento deverá salvar:

```text
Ultron commit
model
model hash
quantization
prompt version
configuration
benchmark version
random seed
hardware
results
```

Sem isso, não teremos pesquisa confiável.

---

# 77. Primeiros milestones

## M0 — Foundation

Entregáveis:

```text
repository
config
logging
SQLite
API
UI shell
event system
health system
```

**Done quando:** Ultron inicia e reinicia preservando estado.

---

## M1 — Local Brain

Adicionar:

```text
Model Gateway
llama.cpp
Ollama
model registry
structured generation
```

**Done quando:** conversa completamente local funciona.

---

## M2 — Agent

Adicionar:

```text
tasks
plans
state machine
tools
policy engine
verifier
```

**Done quando:** executa autonomamente missões multi-step dentro do workspace.

---

## M3 — Persistent Intelligence

Adicionar:

```text
episodic memory
semantic memory
procedural memory
retrieval
consolidation
```

**Done quando:** utiliza corretamente uma experiência antiga em uma nova tarefa.

---

## M4 — Learning Agent

Adicionar:

```text
experience extraction
skills
skill scoring
curriculum
self-model
```

**Done quando:** desempenho melhora após exposição repetida a uma classe de problemas.

---

## M5 — Long-horizon Agent

Adicionar:

```text
missions
checkpoints
task decomposition
replanning
error recovery
```

**Done quando:** realiza tarefas de dezenas de passos mantendo coerência.

---

## M6 — Experimental Self-Improvement

Adicionar:

```text
hypothesis generator
experiment branches
benchmark comparison
regression detection
improvement proposals
```

**Done quando:** Ultron encontra uma deficiência real, produz uma alteração e demonstra objetivamente que a versão experimental melhora o benchmark.

---

## M7 — Generalist Research Agent

Adicionar:

```text
cross-domain benchmark
novel tool learning
transfer learning
research loops
world model
```

---

# 78. Sequência correta de construção

Não construir tudo simultaneamente.

A ordem obrigatória deverá ser:

```text
CORE
 ↓
MODEL
 ↓
TOOLS
 ↓
VERIFICATION
 ↓
MEMORY
 ↓
LEARNING
 ↓
BENCHMARKS
 ↓
SELF-IMPROVEMENT
```

**Self-improvement vem por último.**

Caso contrário, não teremos como saber se uma alteração realmente melhorou o sistema.

---

# 79. Primeira missão oficial

Quando M3 estiver pronto:

> **“Aprenda a desenvolver aplicações Python progressivamente melhores.”**

O Ultron receberá diferentes desafios.

Para cada um:

```text
understand
↓
plan
↓
implement
↓
test
↓
debug
↓
evaluate
↓
reflect
↓
store experience
```

---

# 80. Experimento-chave

Selecionar um conjunto fixo de problemas inéditos.

Executar:

```text
ULTRON FRESH
```

Registrar score.

Depois disponibilizar uma grande série de experiências relacionadas.

Executar novamente o mesmo tipo de benchmark com problemas inéditos.

Hipótese:

```text
Ultron experiente
>
Ultron fresh
```

Mantendo exatamente o mesmo LLM.

Se isso ocorrer consistentemente, teremos evidência de **aprendizado sistêmico real**.

---

# 81. Experimento de ablação

Precisamos saber de onde surge o ganho.

Comparar:

```text
LLM puro

LLM + tools

LLM + tools + memory

LLM + tools + memory + skills

Ultron completo
```

Se o Ultron completo não superar consistentemente o LLM puro, a arquitetura precisa ser revista.

---

# 82. Métrica principal do projeto

Não será:

```text
tokens por segundo
```

nem:

```text
benchmark do LLM
```

Será:

# Capability Gain From Experience

Formalmente:

```text
CGFE =
future performance with experience
-
future performance without experience
```

Esse número deverá orientar o projeto.

---

# 83. Critério para começarmos a falar seriamente em AGI

Não haverá uma linha arbitrária como:

```text
80% = AGI
```

Antes de qualquer discussão desse tipo, o sistema deverá demonstrar simultaneamente:

```text
generalidade
aprendizado contínuo
transferência
planejamento longo
uso de ferramentas
recuperação de erros
memória persistente útil
aquisição de novas habilidades
metacognição
adaptação a tarefas inéditas
```

E tudo isso deverá ser demonstrado em tarefas externas e mensuráveis.

---

# 84. Arquitetura futura

Se o projeto funcionar, a evolução natural será:

```text
Ultron v0
Local assistant

        ↓

Ultron v1
Tool agent

        ↓

Ultron v2
Persistent agent

        ↓

Ultron v3
Learning agent

        ↓

Ultron v4
Self-improving system

        ↓

Ultron v5
Generalist agent

        ↓

Ultron v6
Autonomous research system

        ↓

?

Artificial General Intelligence
```

Não sabemos previamente se a última transição acontecerá.

Esse é justamente o experimento.

---

# 85. Decisão técnica sobre Ling-3.0-tiny

O Ultron não deverá ter Ling codificado diretamente em nenhuma camada cognitiva.

Implementar:

```text
ModelProvider
```

e cadastrar Ling no:

```text
ModelRegistry
```

Isso é essencial porque a velocidade de evolução atual significa que provavelmente surgirão modelos locais melhores durante o próprio desenvolvimento.

Existem atualmente quantizações GGUF comunitárias do Ling utilizáveis através do `llama.cpp`, inclusive Q4_K_M, mas elas devem ser tratadas como artefatos derivados e testadas contra checksum e benchmark antes de serem adotadas como modelo padrão.

---

# 86. Requisito offline

Após modelos e dependências serem instalados, o seguinte deverá funcionar sem internet:

```text
UI
chat
planning
coding
filesystem tools
shell
Python
Git local
memory
learning
benchmarks
experiments
```

---

# 87. Requisito de privacidade

Por padrão:

```text
telemetry_external = false
cloud_llm = false
remote_storage = false
```

O Ultron poderá funcionar sem transmitir tarefas, memória ou documentos para terceiros.

---

# 88. Requisito de portabilidade

Toda a inteligência persistente deverá estar dentro de:

```text
/data
/config
/skills
```

O usuário deverá conseguir transferir o Ultron para outro computador copiando esses diretórios e os modelos necessários.

---

# 89. Critérios mínimos do MVP

O **Ultron Local MVP** estará concluído somente quando puder:

1. iniciar com um comando no Windows;
2. utilizar um LLM totalmente local;
3. receber um objetivo;
4. decompor o objetivo;
5. criar plano;
6. executar ferramentas;
7. observar resultados;
8. detectar falhas;
9. replanejar;
10. concluir uma tarefa;
11. armazenar experiência;
12. recuperar experiência posteriormente;
13. demonstrar memória entre reinicializações;
14. mostrar todo o histórico operacional;
15. interromper qualquer tarefa instantaneamente.

---

# 90. Critério do primeiro Ultron verdadeiramente interessante

A próxima barreira será:

> **O mesmo modelo-base deverá apresentar desempenho melhor depois de usar o Ultron por algum tempo do que apresentava no primeiro dia.**

Sem:

```text
upgrade do LLM
fine-tuning manual
alteração manual da resposta
```

Somente através de:

```text
experiência
memória
skills
estratégias
metacognição
```

Esse será o primeiro sinal de que construímos algo diferente de apenas mais um wrapper de LLM.

---

# 91. North Star

A pergunta científica que deverá orientar todas as decisões do projeto será:

> **“O Ultron está ficando mais capaz ou apenas acumulando mais dados?”**

Cada feature deverá contribuir para responder essa pergunta.

---

# 92. Resultado pretendido

O objetivo final do UltronPro não é criar a melhor interface para conversar com um modelo.

É construir uma infraestrutura na qual um agente possa:

```text
experimentar
      ↓
falhar
      ↓
entender a falha
      ↓
aprender
      ↓
preservar o aprendizado
      ↓
transferi-lo
      ↓
medir a melhoria
      ↓
melhorar seu próprio processo
```

A partir daí, o projeto poderá investigar de forma séria até onde essa curva de aprendizado consegue chegar.

**O LLM será o motor.**

**A memória será a experiência.**

**As ferramentas serão as mãos.**

**O world model será a representação do ambiente.**

**O verifier será o mecanismo de contato com a realidade.**

**O benchmark será o juiz.**

**O Learning Engine será o mecanismo de evolução.**

E o **UltronPro será a arquitetura que conecta tudo isso em um sistema persistente.**