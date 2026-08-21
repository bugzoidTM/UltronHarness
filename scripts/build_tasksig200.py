"""Gera o benchmark diagnóstico público TASKSIG-200."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "benchmarks" / "tasksig200" / "tasks.yaml"

FAMILY_STEMS = {
    "structured_validation": "Validar schema yaml do registro operacional",
    "dependency_recovery": "Recuperar dependência package ausente no workspace",
    "state_recovery": "Executar rollback de state autorizado após divergência",
    "planning": "Ordenar workflow segundo precondition de etapas",
    "configuration_repair": "Reparar config de environment do serviço",
}


def build() -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for family, stem in FAMILY_STEMS.items():
        for index in range(1, 33):
            tasks.append({"id": f"known-{family}-{index:03d}", "objective": f"{stem}; caso diagnóstico {index:03d}.", "expected_family": family})
    for index in range(1, 41):
        tasks.append({"id": f"unknown-{index:03d}", "objective": f"Resumir material conceitual sem procedimento técnico definido; caso externo {index:03d}.", "expected_family": "unknown"})
    if len(tasks) != 200:
        raise RuntimeError("TASKSIG-200 exige duzentas tarefas")
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(build(), allow_unicode=True, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
