# UltronPro — Guia do Research Cycle

O research plane mede ganho de capacidade de forma **local, reproduzível e auditável**. Ele não modifica automaticamente o código do produto nem promove procedimentos sem evidência repetida.

## Pré-requisitos

Inicie o runtime local e confirme o modelo configurado. No Windows, a partir da raiz do projeto, execute:

```powershell
.\scripts\start.ps1
.\.venv\Scripts\python.exe -m ultron.benchmarks run ugib-lite --mode ultron-fresh --seed 42
```

## Ciclo CGFE

O comando abaixo executa, na mesma configuração, uma condição *fresh*, consolida 50 experiências procedurais que não contêm objetivos, IDs, fixtures ou contratos privados do UGIB-Lite, e executa a condição *experienced*.

```powershell
.\.venv\Scripts\python.exe -m ultron.benchmarks cgfe --seed 42 --experiences 50
```

O resultado registra `fresh_score`, `experienced_score`, `cgfe`, `recovery_gain` e `efficiency_gain` em `data/artifacts/experiments/<id>/cgfe.json` e `cgfe.md`. O valor de **CGFE** é `experienced_score − fresh_score`. A seed é enviada às opções do Ollama e também é preservada no manifesto de cada run. Um valor positivo é uma observação de ganho nesta configuração; zero ou negativo também deve ser preservado e investigado, sem seleção silenciosa de resultados.

## Skills e experiências

Uma experiência só é consolidada quando há sucesso, falha nova, recuperação nova ou lição de alto valor. Skills começam como candidatas e só se tornam reutilizáveis após pelo menos três usos e taxa de sucesso mínima de 0,66. Não há merge automático em produção.

## Ablações

As variantes A–F mantêm modelo, seed e benchmark constantes: LLM only; LLM+tools; LLM+tools+orchestrator; Ultron sem memória; Ultron com memória; e Ultron com memória+skills. A política marca regressão quando a diferença contra C é menor que -0,02. Os relatórios são gravados em `data/artifacts/reports/`.

```powershell
.\.venv\Scripts\python.exe -m ultron.benchmarks ablate --seed 42
```

A interface mostra runs, CGFE, ablações e agregados por modelo em **Research**. O mesmo resumo é fornecido pela API local em `GET /api/research/dashboard`.

## Validação

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --cov=ultron --cov-branch
.\.venv\Scripts\python.exe -m pytest tests_security_windows -q
.\.venv\Scripts\python.exe -m pytest tests_agent -m agent -q
.\.venv\Scripts\python.exe -m ruff check ultron tests tests_security_windows apps\api
```

Execute o CGFE pelo menos três vezes com o mesmo commit, modelo e seed e arquive os manifestos antes de inferir um efeito estável.
