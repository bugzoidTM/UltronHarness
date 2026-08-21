# UltronPro — Validação Final Operacional

**Estado:** produto local em funcionamento, com API e interface iniciadas pelo lançador Windows. A validação foi executada contra o modelo local configurado, `qwen2.5:0.5b` via Ollama, e mantém o armazenamento local em SQLite/WAL e Qdrant.

## Evidência de execução

| Área | Evidência | Resultado |
|---|---|---|
| API e interface | `scripts/start.ps1 -NoBrowser`; verificação HTTP local | API responde em `127.0.0.1:8741`; UI responde `200` em `127.0.0.1:5173` |
| Painel Research | `GET /api/research/dashboard` | 20 benchmark runs e 6 relatórios CGFE disponíveis na validação |
| Testes determinísticos | `pytest tests -q --cov=ultron --cov-branch` | **20 passed**, cobertura **70,03%**; gate ≥70% aprovado |
| Segurança Windows | `pytest tests_security_windows -q` | **12 passed, 1 skipped**; traversal, UNC, device paths, expansão de ambiente, symlink e shells aninhados cobertos |
| Testes cognitivos | `pytest tests_agent -m agent -q` | **9 passed, 1 xfailed** com runtime local real |
| Lint | `ruff check ultron tests tests_security_windows apps/api` | **All checks passed** |

## Research plane entregue

O orquestrador agora classifica falhas de ferramenta, persiste sua categoria e estratégia de recuperação, emite evento de falha classificada e só então considera replanejamento. O ciclo de experiência filtra eventos triviais; skills só ficam reutilizáveis quando alcançam pelo menos três usos e taxa de sucesso de 0,66.

O experimento CGFE produz duas condições isoladas: **fresh** e **experienced**. O corpus de experiência é procedural, não contém objetivos, IDs, fixtures ou contratos privados do UGIB-Lite e sofre uma barreira explícita contra vazamento. A seed do benchmark é incluída no manifesto e encaminhada ao runtime Ollama.

| Repetição com seed 42 | Fresh | Experienced | CGFE |
|---|---:|---:|---:|
| Execução com seed propagada 1 | 0,40 | 0,40 | 0,00 |
| Execução com seed propagada 2 | 0,40 | 0,40 | 0,00 |

> O resultado nulo é preservado como evidência válida: nesta configuração, o modelo local e o corpus procedimental não demonstraram ganho medido no UGIB-Lite. O sistema não seleciona nem mascara resultados negativos ou nulos.

## Ablações A–F

O estudo executado com modelo e seed constantes produziu o relatório persistido em `data/artifacts/reports/`. A referência de regressão é a variante C, e uma diferença inferior a -0,02 é marcada como regressão.

| Variante | Configuração | Score | Δ vs C | Política |
|---|---|---:|---:|---|
| A | LLM only | 0,30 | -0,15 | regressão |
| B | LLM + tools | 0,50 | +0,05 | não regressiva |
| C | LLM + tools + orchestrator | 0,45 | 0,00 | referência |
| D | Ultron + memory disabled | 0,35 | -0,10 | regressão |
| E | Ultron + memory | 0,30 | -0,15 | regressão |
| F | Ultron + memory + skills | 0,35 | -0,10 | regressão |

Esses números são observações específicas da execução local e não alegações gerais de superioridade. A política impede que qualquer candidato seja promovido automaticamente.

## Operação

```powershell
# Inicializa API e UI locais
.\scripts\start.ps1

# Executa CGFE e ablações
.\.venv\Scripts\python.exe -m ultron.benchmarks cgfe --seed 42 --experiences 50
.\.venv\Scripts\python.exe -m ultron.benchmarks ablate --seed 42
```

A documentação de operação detalhada está em [RESEARCH_CYCLE_GUIDE.md](RESEARCH_CYCLE_GUIDE.md). O painel **Research** exibe benchmark runs, a última comparação CGFE, agregados por modelo, e a política de ablação/regressão a partir do endpoint local `/api/research/dashboard`.
