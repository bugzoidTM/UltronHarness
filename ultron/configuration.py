"""Configuração central do UltronPro, carregada exclusivamente de arquivos locais."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Mescla mapas recursivamente sem alterar os objetos de entrada."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass(slots=True)
class Settings:
    raw: dict[str, Any]
    root_dir: Path = ROOT_DIR
    data_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    workspace_root: Path = field(init=False)
    artifacts_dir: Path = field(init=False)
    backups_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.root_dir / "data"
        self.db_path = self.data_dir / "ultron.db"
        workspace = self.raw["workspace"]["root"]
        self.workspace_root = (self.root_dir / workspace).resolve()
        self.artifacts_dir = self.data_dir / "artifacts"
        self.backups_dir = self.data_dir / "backups"
        for directory in (
            self.data_dir,
            self.workspace_root,
            self.artifacts_dir,
            self.backups_dir,
            self.data_dir / "vectors",
            self.data_dir / "browser_profiles" / "ultron",
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def host(self) -> str:
        return str(self.raw["system"]["host"])

    @property
    def port(self) -> int:
        return int(self.raw["system"]["port"])

    @property
    def limits(self) -> dict[str, int]:
        return self.raw["limits"]

    @property
    def autonomy_mode(self) -> int:
        return int(self.raw["autonomy"]["mode"])

    @property
    def private_benchmark_root(self) -> Path | None:
        configured = self.raw.get("research", {}).get("private_benchmark_root")
        return Path(str(configured)).expanduser().resolve() if configured else None


def load_settings(root_dir: Path | None = None) -> Settings:
    root = root_dir or ROOT_DIR
    config_dir = root / "config"
    with (config_dir / "default.yaml").open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    local_file = config_dir / "local.yaml"
    if local_file.exists():
        with local_file.open("r", encoding="utf-8") as file:
            raw = _merge(raw, yaml.safe_load(file) or {})
    if model_override := os.getenv("ULTRON_MODEL_PRIMARY"):
        raw["models"]["primary"] = model_override
    if vector_override := os.getenv("ULTRON_VECTOR_ENABLED"):
        raw["memory"]["vector_enabled"] = vector_override.casefold() in {"1", "true", "yes"}
    if private_root := os.getenv("ULTRON_PRIVATE_BENCHMARK_ROOT"):
        raw.setdefault("research", {})["private_benchmark_root"] = private_root
    return Settings(raw=raw, root_dir=root)
