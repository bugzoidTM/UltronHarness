"""Diagnóstico pós-hoc da interface de saída estruturada do Genesis (não confirmatório).

Motivação: na v2-FINAL-OBS, modelos de 3B a 14B produziram respostas diretas degeneradas
(por exemplo, "w" para uma conta trivial) e loops de REPRESENT/HYPOTHESIZE com listas
vazias. Este script testa se a causa está na interface de decodificação restrita por
schema, e não na arquitetura executiva ou no tamanho do modelo.

Ele nunca usa as tarefas do protocolo (reasoning_06/07), o diagnóstico (reasoning_01/02)
nem qualquer benchmark privado. Os itens são sintéticos, da mesma forma pública, e o
gabarito é derivado pela mesma fórmula pública do verificador. Nenhum resultado daqui
altera o veredito pré-registrado da v2-FINAL-OBS.

D1 — resposta direta: mesmas mensagens da condição A, com (a) schema estrito
     FinalAnswerOutput, (b) format=json sem schema e (c) texto livre. Com
     --variants, (d) `schema_nolen` usa o mesmo schema sem minLength/maxLength e
     (e) `schema_prompted` usa o schema estrito e também descreve o formato no prompt.
D2 — conteúdo opcional: REPRESENT e HYPOTHESIZE com os schemas atuais (conteúdo
     opcional) e com variantes em que o conteúdo é obrigatório e não vazio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ultron.benchmarks.models import BenchmarkTask
from ultron.configuration import load_settings
from ultron.genesis.public_runner import GenesisPublicRunner, _public_answer
from ultron.genesis.schemas import (
    CognitiveFrame,
    FinalAnswerOutput,
    GenesisOperator,
    HypothesisOutput,
    RepresentationOutput,
    ShortText,
)
from ultron.genesis.vm import CognitiveVM
from ultron.models.gateway import ModelGateway

SEED = 42
ITEMS = (
    "Calcule 36 dividido por 4 e some 5. Responda somente com o número.",
    "Calcule 12 multiplicado por 3 e some 5. Responda somente com o número final.",
    "A sequência é 3, 12, 48, 192. Qual é o próximo número? Responda somente com o número.",
    "Calcule 45 dividido por 9 e some 8. Responda somente com o número.",
    "A sequência é 5, 10, 20, 40. Qual é o próximo número? Responda somente com o número.",
    "Calcule 14 multiplicado por 2 e some 9. Responda somente com o número final.",
    "Calcule 63 dividido por 7 e some 3. Responda somente com o número.",
    "A sequência é 1, 4, 16, 64. Qual é o próximo número? Responda somente com o número.",
)
REPRESENT_INSTRUCTION = "Transforme o problema em uma representação factual. Extraia entidades, fatos, restrições e incógnitas sem resolver a tarefa. Inclua next_operator com a próxima primitiva cognitiva desejada."
HYPOTHESIZE_INSTRUCTION = "Proponha hipóteses candidatas e previsões testáveis a partir do frame atual. Não escolha nem anuncie uma resposta final. Inclua next_operator com a próxima primitiva cognitiva desejada."


class RequiredRepresentationOutput(BaseModel):
    entities: list[ShortText] = Field(min_length=1, max_length=4)
    facts: list[ShortText] = Field(min_length=1, max_length=4)
    constraints: list[ShortText] = Field(min_length=1, max_length=4)
    unknowns: list[ShortText] = Field(min_length=1, max_length=4)
    next_operator: GenesisOperator


class RequiredHypothesisOutput(BaseModel):
    hypotheses: list[ShortText] = Field(min_length=1, max_length=2)
    predictions: list[ShortText] = Field(min_length=1, max_length=2)
    next_operator: GenesisOperator


def _task(index: int, objective: str) -> BenchmarkTask:
    return BenchmarkTask(id=f"diagnostic_{index:02d}", category="reasoning", objective=objective, evaluator="exact")


def _parse_answer(content: str) -> str:
    try:
        loaded = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    if isinstance(loaded, dict):
        for key in ("answer", "resposta", "result", "resultado"):
            if key in loaded:
                return str(loaded[key]).strip()
    return content.strip()


SCHEMA_HINT = 'Formato obrigatório: {"answer": "<resposta final, somente o valor pedido>"}.'


async def _direct(gateway: ModelGateway, model: str, messages: list[dict[str, str]], variant: str) -> str:
    provider = gateway.provider(model)
    kwargs: dict[str, Any] = {"seed": SEED, "temperature": 0.2, "max_tokens": 1792}
    if variant == "schema_prompted":
        messages = [{**messages[0], "content": f"{messages[0]['content']} {SCHEMA_HINT}"}, *messages[1:]]
    if variant in {"schema", "schema_prompted"}:
        kwargs["json_schema"] = FinalAnswerOutput.model_json_schema()
    elif variant == "schema_nolen":
        kwargs["json_schema"] = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    elif variant == "json":
        kwargs["json_mode"] = True
    response = await provider.generate(messages, **kwargs)
    return response.content


def last_number(text: str) -> str | None:
    """Último inteiro do texto; métrica descritiva que separa formato de raciocínio."""
    numbers = re.findall(r"-?\d+(?:[.,]\d+)?", text)
    if not numbers:
        return None
    value = numbers[-1].replace(",", ".")
    return str(int(float(value))) if float(value).is_integer() else value


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    d1_rows = result["D1"]
    variants = tuple(result.get("d1_variants", ("schema", "json", "text")))
    summary: dict[str, Any] = {
        "D1_exact_rate": {variant: round(sum(int(row[variant]["exact"]) for row in d1_rows) / len(d1_rows), 3) for variant in variants},
        "D1_last_number_rate": {variant: round(sum(int(last_number(row[variant]["answer"]) == row["expected"]) for row in d1_rows) / len(d1_rows), 3) for variant in variants},
    }
    d2_rows = result["D2"]
    if d2_rows:
        labels = ("represent_optional", "represent_required", "hypothesize_optional", "hypothesize_required")
        summary["D2_empty_or_invalid_rate"] = {label: round(sum(int(row[label]["empty"]) for row in d2_rows) / len(d2_rows), 3) for label in labels}
        summary["D2_schema_error_rate"] = {label: round(sum(int(row[label]["error"] is not None) for row in d2_rows) / len(d2_rows), 3) for label in labels}
    return summary


def _empty_content(output: BaseModel) -> bool:
    values = output.model_dump(exclude={"next_operator"})
    return all(not value for value in values.values())


async def run(model: str, output: Path, skip_d2: bool, variants: tuple[str, ...] = ("schema", "json", "text")) -> dict[str, Any]:
    settings = load_settings(Path(__file__).resolve().parents[1])
    settings.raw["models"]["timeout_seconds"] = 600
    gateway = ModelGateway(settings)
    tasks = [_task(index, objective) for index, objective in enumerate(ITEMS, start=1)]
    d1_rows = []
    for task in tasks:
        expected = _public_answer(task.objective)
        messages = GenesisPublicRunner._messages(task, "direct", None, 1)
        row: dict[str, Any] = {"task_id": task.id, "expected": expected}
        for variant in variants:
            try:
                raw = await _direct(gateway, model, messages, variant)
            except Exception as exc:  # erro de runtime é registrado, não pontuado como acerto
                raw = f"RUNTIME_ERROR:{type(exc).__name__}:{str(exc)[:120]}"
            answer = _parse_answer(raw) if variant != "text" else raw.strip()
            row[variant] = {"raw": raw[:400], "answer": answer[:200], "exact": answer.casefold().strip() == expected}
        d1_rows.append(row)
    d2_rows = []
    if not skip_d2:
        vm = CognitiveVM(gateway, model_name=model, seed=SEED, max_tokens=256)
        for task in tasks:
            frame = CognitiveFrame(problem=task.objective)
            row = {"task_id": task.id}
            for label, schema, instruction in (
                ("represent_optional", RepresentationOutput, REPRESENT_INSTRUCTION),
                ("represent_required", RequiredRepresentationOutput, REPRESENT_INSTRUCTION),
                ("hypothesize_optional", HypothesisOutput, HYPOTHESIZE_INSTRUCTION),
                ("hypothesize_required", RequiredHypothesisOutput, HYPOTHESIZE_INSTRUCTION),
            ):
                try:
                    parsed = await vm._structured(schema, instruction, frame)
                    row[label] = {"empty": _empty_content(parsed), "error": None, "output": parsed.model_dump(mode="json")}
                except Exception as exc:  # erro de schema é dado do diagnóstico
                    row[label] = {"empty": True, "error": f"{type(exc).__name__}:{str(exc)[:160]}", "output": None}
            d2_rows.append(row)
    result = {
        "diagnostic": "genesis-interface-posthoc",
        "confirmatory": False,
        "protocol_tasks_used": False,
        "model": model,
        "model_tag": settings.raw["models"]["registry"][model]["model"],
        "seed": SEED,
        "items": len(tasks),
        "d1_variants": list(variants),
        "D1": d1_rows,
        "D2": d2_rows,
    }
    result["summary"] = summarize(result)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"genesis_interface_{model}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico pós-hoc da interface estruturada do Genesis.")
    parser.add_argument("--model", default="ollama_research_7b")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/research/genesis_interface_diagnostic"))
    parser.add_argument("--skip-d2", action="store_true")
    parser.add_argument("--variants", nargs="+", choices=("schema", "schema_nolen", "schema_prompted", "json", "text"), default=["schema", "json", "text"])
    parser.add_argument("--resummarize", type=Path, nargs="+", help="recalcula o resumo de JSONs já salvos, sem chamar modelos")
    args = parser.parse_args()
    if args.resummarize:
        for path in args.resummarize:
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved["summary"] = summarize(saved)
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"model": saved["model_tag"], **saved["summary"]}, ensure_ascii=False))
        return 0
    result = asyncio.run(run(args.model, args.output, args.skip_d2, tuple(args.variants)))
    print(json.dumps({"model": result["model_tag"], **result["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
