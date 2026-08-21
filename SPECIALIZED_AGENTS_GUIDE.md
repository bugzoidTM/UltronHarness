# Guia Operacional — Agentes Especializados no UltronPro

> **Versão de referência:** UltronPro 0.1.0 local.  
> **Escopo:** configuração e operação de agentes especializados sem alterar o plano de controle, a política ou a persistência canônica da plataforma.

## 1. Modelo atual de especialização

No estado atual do UltronPro, um agente especializado **não é um plugin ou uma classe isolada de agente**. A especialização é uma composição operacional de cinco elementos: um **objetivo permanente**, uma **tarefa com instrução especializada**, um **workspace isolado**, um **modo de autonomia** e um conjunto de **memórias de domínio**. Todos esses elementos são persistidos e rastreáveis.

Em termos práticos, cada novo especialista é iniciado como uma missão com identidade própria. A missão cria ou reutiliza o diretório `data/workspaces/<nome-do-workspace>/`, recupera memórias relevantes, elabora um plano, aplica a política de risco em cada etapa, executa ferramentas permitidas e consolida lições no encerramento.

| Elemento | Função na especialização | Persistência |
|---|---|---|
| Objetivo (`Goal`) | Define a finalidade contínua e a métrica de sucesso | SQLite: `goals` |
| Tarefa (`Task`) | Define o papel, escopo, critérios de aceitação e limites da execução atual | SQLite: `tasks` |
| Workspace | Isola arquivos e artefatos da missão | `data/workspaces/<workspace>/` |
| Memórias | Introduzem procedimentos, fatos e experiências do domínio | SQLite: `memories` |
| Política | Controla ferramentas, riscos, aprovações e bloqueios | `config/default.yaml` + Policy Engine |

> **Consequência importante:** o texto de objetivo especializa o comportamento cognitivo; contudo, a restrição de ferramentas é global na versão 0.1.0. Se for necessário impedir tecnicamente que determinado especialista use uma ferramenta, essa regra deve ser adicionada ao `PolicyEngine` ou ao `ToolRegistry`; apenas descrever a proibição no objetivo não é um controle de segurança suficiente.

## 2. Pré-requisitos e inicialização da plataforma

Abra PowerShell no diretório local do projeto e inicie a plataforma. O launcher inicia a API em `127.0.0.1:8741` e a interface em `127.0.0.1:5173`.

```powershell
cd "D:\sistemas\Nova pasta\UltronHarness"
.\scripts\start.ps1
```

Antes de iniciar um novo especialista, valide a saúde dos serviços e do modelo configurado.

```powershell
Invoke-RestMethod http://127.0.0.1:8741/api/system/health
Invoke-RestMethod http://127.0.0.1:8741/api/models
```

A configuração padrão usa Ollama com `qwen2.5:0.5b`. Para trocar o motor cognitivo local, modifique uma cópia local de configuração (`config/local.yaml`) ou ajuste `config/default.yaml`, e reinicie a API.

```yaml
models:
  primary: ollama
  registry:
    ollama:
      provider: ollama
      endpoint: http://127.0.0.1:11434
      model: qwen2.5:0.5b
      enabled: true
      roles: [planning, reasoning, tools]
```

O campo `roles` descreve a finalidade pretendida do runtime, mas a versão atual ainda não possui roteamento automático de modelo por especialista. O `primary` seleciona o modelo usado pelo gateway, salvo quando a aplicação for estendida para passar explicitamente outro `model_name`.

## 3. Definição segura do perfil especializado

A qualidade de um especialista depende de um contrato operacional claro. Todo objetivo deve especificar o resultado esperado, o domínio, quais evidências aceitas comprovam sucesso, os limites de atuação e o formato de entrega. Evite instruções vagas como “pesquise tudo” ou “faça o necessário”; elas aumentam a ambiguidade do plano e a probabilidade de replanejamentos.

Use o seguinte modelo ao escrever o campo `objective` da tarefa:

```text
Você é um especialista em <domínio>.

Resultado obrigatório: <artefato ou decisão verificável>.
Contexto disponível: <arquivos, dados, convenções ou memória relevante>.
Escopo permitido: <ações, diretório de trabalho e limite operacional>.
Restrições: <ações proibidas, ausência de rede, necessidade de aprovação>.
Evidência de sucesso: <testes, arquivo, relatório, diff ou condição objetiva>.
Formato da entrega: <estrutura concisa e verificável>.
```

| Especialista | Objetivo operacional típico | Workspace recomendado | Autonomia inicial |
|---|---|---|---:|
| Revisor de código | Inspecionar mudanças, apontar riscos e propor correções sem modificar arquivos | `code_review` | 2 |
| Analista de dados | Examinar CSVs locais, produzir métricas e relatório Markdown | `data_analysis` | 2 |
| Autor técnico | Criar documentação baseada em arquivos do projeto e validar links internos | `technical_writing` | 2 |
| Agente de manutenção | Criar patch pequeno, executar testes e submeter para aprovação | `maintenance` | 2 |
| Cientista de experimentos | Preparar benchmark, comparar baseline/candidato e registrar resultados | `experiments` | 2 |

## 4. Escolha do modo de autonomia e política

O campo `autonomy_mode` é definido por tarefa e aceita valores de `0` a `4`. Na implementação atual, os modos `0` e `1` possuem comportamento próprio explícito; para valores superiores, a decisão efetiva depende principalmente do risco da ferramenta e da lista `security.require_approval_for`.

| Modo | Efeito implementado | Uso recomendado |
|---:|---|---|
| `0` | Não permite execução de ferramentas | Conversa, análise e planejamento sem ação operacional |
| `1` | Exige confirmação para qualquer ferramenta | Especialista exploratório com intervenção humana constante |
| `2` | Opera sob política supervisionada padrão | Ponto de partida recomendado para novos especialistas |
| `3`–`4` | Não recebem privilégio absoluto; R3/R4 continuam exigindo aprovação | Apenas após validar escopo, memórias e ferramentas |

A política padrão também exige aprovação para `R2`, `R3` e `R4`. Portanto, mesmo uma tarefa com `autonomy_mode: 3` continuará aguardando aprovação para uma escrita `file.write` enquanto `R2` permanecer em `security.require_approval_for`.

> **Regra operacional:** crie todos os especialistas inicialmente no modo `2`. Ele permite leitura e execução de baixo risco, mas interrompe modificações antes de aplicá-las. Aumente a autonomia apenas depois de validar tarefas representativas no smoke test do domínio.

As ferramentas atuais e seus riscos principais são os seguintes.

| Ferramenta | Risco | Aprovação padrão | Aplicação típica |
|---|---|---|---|
| `file.list`, `file.read`, `file.search` | R0 | Não | Auditoria, análise, documentação |
| `git.status`, `git.diff`, `git.log` | R0 | Não | Revisão de código e diagnóstico |
| `python.execute` | R1 | Não | Cálculo, parsing e validação local |
| `file.write`, `file.delete` | R2 | Sim | Patches, relatórios, artefatos de dados |
| `shell.run` | R2 | Sim | Ferramentas de build e testes controlados |

Os comandos shell são executados sem `shell=True`, dentro do workspace, com timeout. A política bloqueia padrões de sistema destrutivos, e qualquer caminho fora do workspace é rejeitado.

## 5. Criar memórias de domínio antes da primeira missão

Memórias iniciais reduzem o tempo de adaptação do especialista. Para um revisor de código, grave convenções de estilo; para um analista de dados, grave dicionários de dados e métricas válidas; para um especialista de documentação, grave padrões editoriais e estrutura esperada.

O exemplo abaixo registra uma memória procedural para um especialista de revisão Python.

```powershell
$memory = @{
  type = "procedural"
  content = "Ao revisar código Python: verifique entradas não validadas, acesso fora do workspace, subprocessos sem timeout, dependências ausentes e cobertura de testes. Produza achados por severidade e arquivo."
  summary = "Checklist de revisão Python segura"
  importance = 0.85
  confidence = 0.90
  source = "operator"
  provenance = "Política interna de engenharia"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8741/api/memories" `
  -ContentType "application/json" `
  -Body $memory
```

Use `type = "semantic"` para fatos e convenções, `"procedural"` para métodos reutilizáveis e `"world"` para a topologia local. A busca e a recuperação ocorrem automaticamente durante o planejamento; também podem ser consultadas por `POST /api/memories/search`.

## 6. Criar objetivo e tarefa especializada pela API

O procedimento abaixo cria um objetivo, gera uma missão especializada e inicia o orquestrador. A mesma operação pode ser feita no dashboard, mas a API é mais adequada para padronizar perfis repetíveis.

### 6.1 Criar o objetivo persistente

```powershell
$goalPayload = @{
  title = "Elevar a qualidade de código Python local"
  description = "Revisar mudanças de código, identificar riscos e produzir recomendações verificáveis sem modificar o repositório."
  priority = 0.8
  success_metric = "Relatório com achados priorizados e evidências por arquivo"
} | ConvertTo-Json

$goal = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8741/api/goals" `
  -ContentType "application/json" `
  -Body $goalPayload
```

### 6.2 Criar um especialista revisor de código

```powershell
$taskPayload = @{
  title = "Especialista: revisão de código Python"
  goal_id = $goal.id
  priority = 0.8
  workspace = "code_review"
  autonomy_mode = 2
  objective = @"
Você é um especialista em revisão de código Python local.

Resultado obrigatório: produza um relatório Markdown de achados classificados por severidade, arquivo e evidência.
Contexto disponível: examine somente arquivos presentes no workspace code_review.
Escopo permitido: listar, ler, buscar texto e analisar diffs Git; não altere arquivos sem aprovação explícita.
Restrições: não use rede, não acesse caminhos externos ao workspace e não execute comandos destrutivos.
Evidência de sucesso: cada achado deve citar caminho, linha ou trecho e propor uma correção verificável.
Formato da entrega: Resumo executivo, achados críticos, achados moderados e recomendações.
"@
} | ConvertTo-Json

$task = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8741/api/tasks" `
  -ContentType "application/json" `
  -Body $taskPayload
```

O nome de workspace aceita apenas letras, dígitos, `_` e `-`. O UltronPro cria automaticamente o diretório seguro correspondente abaixo de `data/workspaces/`.

### 6.3 Inserir dados no workspace e iniciar

Copie os arquivos de trabalho para o workspace recém-criado antes de iniciar a missão. Para o exemplo anterior, o diretório será `data/workspaces/code_review/`.

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8741/api/tasks/$($task.id)/run"
```

O retorno inicial sinaliza que a missão foi enfileirada. O estado real evolui em segundo plano por `planning`, `running`, `waiting_approval`, `completed`, `failed` ou `cancelled`.

## 7. Supervisão, aprovação e encerramento

Inspecione o estado completo, planos, eventos, ferramentas e aprovações pendentes com o endpoint da tarefa.

```powershell
Invoke-RestMethod "http://127.0.0.1:8741/api/tasks/$($task.id)"
Invoke-RestMethod "http://127.0.0.1:8741/api/tasks/$($task.id)/timeline"
```

Quando houver uma ação R2/R3/R4, a tarefa entrará em `waiting_approval`. A aprovação pode ser realizada pelo painel ou pela API de aprovações. Antes de aprovar, confirme o workspace, o caminho de destino, os argumentos da ferramenta e a condição de sucesso associada ao passo.

```powershell
$approval = Invoke-RestMethod "http://127.0.0.1:8741/api/approvals"
$pending = $approval | Where-Object { $_.task_id -eq $task.id -and $_.status -eq "pending" } | Select-Object -First 1

$decision = @{ approved = $true; note = "Aprovado após revisão do escopo e do workspace." } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8741/api/approvals/$($pending.id)" `
  -ContentType "application/json" `
  -Body $decision
```

Se for necessário pausar ou cancelar somente uma missão, use `POST /api/tasks/{id}/pause` ou `POST /api/tasks/{id}/cancel`. Em situação de emergência, use o botão **STOP ULTRON**, o atalho `Ctrl + Shift + F12` no dashboard ou o endpoint `POST /api/system/stop`. A parada global encerra as tarefas ativas e persiste o estado.

## 8. Criar novos perfis de especialista de forma repetível

Para operacionalizar múltiplos especialistas, mantenha uma pasta de perfis versionados fora de `data/`, por exemplo `config/agents/`. Cada arquivo pode documentar o contrato de objetivo, a configuração de autonomia, as memórias de bootstrap, o workspace e o roteiro de smoke test. O UltronPro 0.1.0 não carrega automaticamente esses arquivos; eles servem como fonte controlada para criar tarefas pela API ou pela UI.

```yaml
name: python_code_reviewer
workspace: code_review
autonomy_mode: 2
model_primary: ollama
bootstrap_memories:
  - type: procedural
    summary: Checklist de revisão Python
success_criteria:
  - Relatório Markdown produzido no workspace
  - Achados incluem evidência por arquivo
  - Nenhuma escrita ocorreu sem aprovação
```

Para criar especialização **tecnicamente reforçada**, implemente um perfil de ferramentas no código. Adicione manifestos e handlers no `ToolRegistry`, atribua um `RiskLevel` apropriado, valide argumentos no handler e amplie o `PolicyEngine` com uma regra por papel, tag ou workspace. Por fim, crie testes de regressão que comprovem tanto o caminho permitido quanto o bloqueado.

| Necessidade | Configuração suficiente | Extensão de código necessária |
|---|---|---|
| Papel com instrução e memória própria | Sim | Não |
| Workspace isolado por especialista | Sim | Não |
| Modelo local global alternativo | Sim | Não |
| Roteamento de modelo por especialista | Não | Sim, no `ModelGateway`/orquestrador |
| Allowlist de ferramentas por especialista | Não | Sim, no `PolicyEngine`/`ToolRegistry` |
| Ferramenta de domínio nova | Não | Sim, com `ToolManifest` e handler |
| Browser seguro ou vetor Qdrant | Parcialmente configurável | Sim, integração e testes específicos |

## 9. Checklist de lançamento de um novo especialista

1. Inicie a plataforma e valide `/api/system/health` e `/api/models`.
2. Defina um objetivo persistente com métrica de sucesso objetiva.
3. Crie ou escolha um workspace exclusivo e copie somente os dados necessários.
4. Escreva o objetivo da tarefa com escopo, restrições e evidências verificáveis.
5. Adicione memórias semânticas e procedurais de bootstrap.
6. Configure `autonomy_mode: 2` para o primeiro ciclo de validação.
7. Execute uma missão pequena e inspecione plano, timeline e ferramentas utilizadas.
8. Aprove manualmente qualquer ação R2/R3/R4 e confirme o artefato produzido.
9. Reexecute uma segunda missão equivalente para validar recuperação de memória e consistência.
10. Somente então amplie autonomia ou implemente um controle de ferramenta específico ao perfil.

## 10. Limitações atuais a considerar

A plataforma já suporta especialização operacional por tarefa, memória, workspace e política. Contudo, os perfis ainda não são entidades de primeira classe com arquivo carregado automaticamente, a seleção de modelo por papel ainda não é roteada automaticamente e não existe allowlist de ferramentas por perfil. Essas limitações não impedem o uso seguro de especialistas supervisionados; elas definem o próximo incremento de engenharia para ambientes com alta diversidade de agentes.
