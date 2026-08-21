"""Executa o gate PRIVACY-1 sem expor valores de contratos privados."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultron.configuration import load_settings
from ultron.learning.transfer import PrivateBenchmarkRootError, resolve_private_contract_root
from ultron.research.leakage import assert_private_contracts_isolated

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="transfer100_v4")
    parser.add_argument("--contract-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = load_settings(ROOT)
    contract_root = resolve_private_contract_root(settings, args.benchmark, args.contract_root)
    if not (contract_root / "answers.json").exists():
        raise PrivateBenchmarkRootError(f"Contrato privado ausente: {contract_root / 'answers.json'}")
    report = assert_private_contracts_isolated(ROOT, contract_root)
    payload = report.as_dict()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
