"""Compatibilidade para o entrypoint da ablação Genesis v0.2.1.

O experimento ativo passou a ser Genesis v0.2.2 Non-Solving Cognitive VM.
Use `scripts/run_genesis_v022.py` para executar o protocolo vigente.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_genesis_v022 import main

if __name__ == "__main__":
    raise SystemExit(main())
