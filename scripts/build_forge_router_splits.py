"""Gera os splits públicos e independentes do experimento Router Learning Forge."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml
from build_transfer100_v4 import build_public_tasks

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "benchmarks" / "forge_router_v1"


def _variant(index: int) -> str:
    if index % 10 < 3:
        return "canonical"
    if index % 10 < 7:
        return "paraphrased"
    return "adversarial"


def _objective(text: str, variant: str, split: str) -> str:
    if split == "calibration":
        return f"Diagnóstico de calibração: avalie o incidente relacionado, mantendo o escopo local: {text}"
    if variant == "canonical":
        return text
    if variant == "paraphrased":
        return f"No ambiente alvo, determine o próximo procedimento seguro para este cenário equivalente: {text}"
    return f"Evite atalhos e inferências não autorizadas. Entre as opções disponíveis, trate esta descrição oblíqua do incidente: {text}"


def _task(source: dict[str, object], split: str, index: int) -> dict[str, object]:
    family = str(source["family"])
    result = dict(source)
    result["id"] = f"forge_{split}_{family}_{index:02d}"
    result["objective"] = _objective(str(source["objective"]), _variant(index), split)
    result["source_domain"] = f"{split}_{source['source_domain']}"
    result["target_domain"] = f"{split}_{source['target_domain']}"
    result["case_key"] = f"forge:{split}:{family}:{index:02d}"
    result["dataset_split"] = split
    result["lexical_variant"] = "calibration" if split == "calibration" else _variant(index)
    return result


def build_splits() -> dict[str, list[dict[str, object]]]:
    base = build_public_tasks()
    splits: dict[str, list[dict[str, object]]] = {}
    for split in ("calibration", "target"):
        per_family: Counter[str] = Counter()
        items: list[dict[str, object]] = []
        for source in base:
            family = str(source["family"])
            per_family[family] += 1
            items.append(_task(source, split, per_family[family]))
        if len(items) != 100 or len({str(item["id"]) for item in items}) != 100:
            raise RuntimeError(f"Split {split} inválido")
        splits[split] = items
    return splits


def write_splits(root: Path = PUBLIC_ROOT) -> dict[str, list[dict[str, object]]]:
    splits = build_splits()
    for split, tasks in splits.items():
        destination = root / split
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "tasks.yaml").write_text(yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (root / "README.md").write_text(
        "# Forge Router Learning v1\n\nCalibration e Target compartilham famílias procedurais, mas possuem identificadores, domínios e formulações independentes. Contratos de ambos os splits são privados e externos ao repositório.\n",
        encoding="utf-8",
    )
    metadata = {
        "benchmark": "forge_router_v1",
        "calibration_tasks": len(splits["calibration"]),
        "target_tasks": len(splits["target"]),
        "target_variants": dict(Counter(str(item["lexical_variant"]) for item in splits["target"])),
    }
    (root / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return splits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=PUBLIC_ROOT)
    args = parser.parse_args()
    write_splits(args.public_root)


if __name__ == "__main__":
    main()
