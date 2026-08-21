"""Auditoria determinística de separação entre corpus público e contratos privados."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PUBLIC_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md"}
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "data", "__pycache__"}


@dataclass(frozen=True, slots=True)
class LeakageMatch:
    path: str
    marker_kind: str
    marker_digest: str


@dataclass(frozen=True, slots=True)
class LeakageReport:
    public_private_overlap: int
    matches: tuple[LeakageMatch, ...]
    scanned_files: int
    private_marker_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "public_private_overlap": self.public_private_overlap,
            "matches": [asdict(item) for item in self.matches],
            "scanned_files": self.scanned_files,
            "private_marker_count": self.private_marker_count,
        }


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _marker(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _private_markers(contract_root: Path) -> dict[str, str]:
    markers: dict[str, str] = {}
    for filename, kind in (("answers.json", "answer_value"), ("fixtures.json", "fixture_value")):
        path = contract_root / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for value in _strings(payload):
            normalized = value.strip()
            if len(normalized) >= 5:
                markers[normalized] = kind
        markers[_marker(json.dumps(payload, ensure_ascii=False, sort_keys=True))] = f"{kind}_hash"
    return markers


def _iter_public_files(repository_root: Path, public_paths: Iterable[Path] | None) -> Iterable[Path]:
    roots = list(public_paths or (repository_root / "benchmarks", repository_root / "scripts", repository_root / "ultron"))
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in PUBLIC_SUFFIXES:
                continue
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            yield path


def scan_repository_for_private_contracts(
    repository_root: Path,
    contract_root: Path,
    public_paths: Iterable[Path] | None = None,
) -> LeakageReport:
    """Procura valores e hashes de contrato em código e datasets públicos.

    O relatório expõe somente hashes dos marcadores encontrados; nunca reproduz
    valores privados nos artefatos públicos de auditoria.
    """
    markers = _private_markers(contract_root)
    matches: list[LeakageMatch] = []
    scanned_files = 0
    for path in _iter_public_files(repository_root, public_paths):
        scanned_files += 1
        content = path.read_text(encoding="utf-8", errors="replace")
        for value, kind in markers.items():
            if value in content:
                matches.append(
                    LeakageMatch(
                        path=str(path.relative_to(repository_root)),
                        marker_kind=kind,
                        marker_digest=_marker(value),
                    )
                )
    return LeakageReport(
        public_private_overlap=len(matches),
        matches=tuple(matches),
        scanned_files=scanned_files,
        private_marker_count=len(markers),
    )


def assert_private_contracts_isolated(
    repository_root: Path,
    contract_root: Path,
    public_paths: Iterable[Path] | None = None,
) -> LeakageReport:
    report = scan_repository_for_private_contracts(repository_root, contract_root, public_paths)
    if report.public_private_overlap:
        raise RuntimeError(
            f"PRIVACY-1 falhou: {report.public_private_overlap} marcador(es) privado(s) encontrado(s) no corpus público."
        )
    return report
