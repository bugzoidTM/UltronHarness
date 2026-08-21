"""Executa WORLD-100 com outcomes reais do Transfer-100 e grava resultado auditável."""

from __future__ import annotations

import json
from dataclasses import asdict

from ultron.configuration import load_settings
from ultron.research.world100 import run_world100_from_transfer


def main() -> None:
    settings = load_settings()
    root = settings.artifacts_dir / "transfer" / "transfer100"
    result = run_world100_from_transfer(root)
    output = settings.artifacts_dir / "research" / "hermes" / "world100"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "world100.json"
    payload = asdict(result)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
