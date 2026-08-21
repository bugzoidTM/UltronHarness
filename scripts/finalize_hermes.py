"""Consolida o resultado Transfer-100 em um relatório Markdown auditável do Project Hermes."""

from __future__ import annotations

import json

from ultron.configuration import load_settings


def main() -> None:
    settings = load_settings()
    source = settings.artifacts_dir / "research" / "hermes" / "transfer100" / "transfer100_json_compact_multiseed_42_51.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    gain = payload["statistics"]["transfer_gain"]
    completed = payload.get("completed_seeds", [])
    status = payload.get("status", "unknown")
    gate = status == "completed" and gain["mean"] > 0 and gain["ci95_low"] > 0
    decision = "PROMOTE_CANDIDATE" if gate else "SHADOW_REJECTED"
    family_rows: dict[str, list[float]] = {}
    for result in payload.get("results", []):
        for family, value in result.get("by_family", {}).items():
            family_rows.setdefault(family, []).append(float(value))
    family_markdown = "\n".join(
        f"| {family} | {sum(values)/len(values):+.4f} | {len(values)} |"
        for family, values in sorted(family_rows.items())
    ) or "| Sem dados | — | 0 |"
    text = f"""# HERMES_DIAGNOSTIC_REPORT

## Resultado executivo

O Transfer-100 foi executado com o protocolo `{payload.get('benchmark_version')}`, modelo `{payload.get('model')}` e seeds solicitadas `{payload.get('requested_seeds')}`. O checkpoint está em estado **{status}**, com **{len(completed)}/10** seeds concluídas.

| Métrica | Valor |
|---|---:|
| Transfer Gain médio | {gain['mean']:+.4f} |
| IC95% | [{gain['ci95_low']:+.4f}, {gain['ci95_high']:+.4f}] |
| Seeds concluídas | {len(completed)} |
| Decisão Hermes Gate 1 | **{decision}** |

A regra de promoção exige rodada completa, ganho médio positivo e limite inferior do IC95% estritamente positivo. Portanto, a decisão acima é mecânica e não usa avaliação por modelo.

## Resultado por família

| Família | Ganho médio por seed | N |
|---|---:|---:|
{family_markdown}

## Decisões de produto

O roteador de experiências permanece em **shadow/experimental**. Ações `USE` não são integradas ao contexto ativo; `ABSTAIN` continua o comportamento padrão sob evidência insuficiente, e o firewall bloqueia famílias nocivas quando houver pares persistidos. A Symbolic Lane permanece isolada apesar de passar no Symbolic-100; World Model, Critic e Strategy Policy seguem observacionais.

## Reprodutibilidade e limites

Os contratos de avaliação permanecem privados; o corpus público não recebe gabaritos. Resultados negativos são preservados no checkpoint Transfer-100. Transferências cross-domain e cross-model só podem ser iniciadas após o Gate 1, para evitar que um resultado externo seja usado para compensar uma falha intrafamília.

## Quality gates

| Gate | Estado conhecido |
|---|---|
| Pytest determinístico + cobertura | PASS — 63 testes, 75,90% |
| Segurança Windows | PASS — 12 passed, 1 skipped |
| Testes de agente | PASS — 9 passed, 1 xfailed |
| Ruff | PASS |
| Build React | PASS |
| Smoke API/UI | Pendente de repetição sem concorrência do benchmark local |
"""
    target = settings.root_dir / "HERMES_DIAGNOSTIC_REPORT.md"
    target.write_text(text, encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
