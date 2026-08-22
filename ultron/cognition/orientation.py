"""Serviço determinístico de orientação inicial compartilhada do ambiente."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ultron.schemas import OrientationSnapshot
from ultron.tools.registry import ToolRegistry


def canonical_json(data: Any) -> str:
    """Serializa estruturas de dados em JSON canônico estável."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_fixture_hash(workspace_path: Path) -> str:
    """Calcula um hash determinístico do estado do fixture em disco."""
    if not workspace_path.exists() or not workspace_path.is_dir():
        return hashlib.sha256(b"").hexdigest()

    file_hashes: list[str] = []
    for path in sorted(workspace_path.rglob("*")):
        if path.is_file():
            rel_path = str(path.relative_to(workspace_path)).replace("\\", "/")
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            file_hashes.append(f"{rel_path}:{content_hash}")

    combined = "\n".join(file_hashes).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def normalize_observations(raw_observations: list[str]) -> list[str]:
    """Normaliza observações removendo IDs efêmeros, timestamps e normalizando separadores."""
    normalized: list[str] = []
    uuid_pattern = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
    iso_timestamp_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")

    for obs in raw_observations:
        text = obs.replace("\r\n", "\n").replace("\\", "/")
        text = uuid_pattern.sub("<EPHEMERAL_ID>", text)
        text = iso_timestamp_pattern.sub("<TIMESTAMP>", text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if all(not line.startswith("(") and ("." in line or line.endswith("/")) for line in lines):
            lines = sorted(lines)
        normalized.append("\n".join(lines))

    return sorted(normalized) if len(normalized) > 1 else normalized


class EnvironmentOrientationService:
    """Constrói percepção inicial autorizada e imutável para os controladores."""

    def __init__(self, tools: ToolRegistry | None = None):
        self.tools = tools

    async def build(
        self,
        task: dict[str, Any],
        *,
        seed: int | None = None,
        workspace_path: Path | None = None,
        tools: ToolRegistry | None = None,
    ) -> OrientationSnapshot:
        mission_id = str(task.get("id") or task.get("mission_id") or "")
        allowed_tools = [str(t) for t in (task.get("allowed_tools") or [])]
        raw_budget = task.get("action_budget")
        action_budget = (int(raw_budget[0]), int(raw_budget[1])) if raw_budget else None

        raw_observations: list[str] = []
        evidence_refs: list[str] = []

        # Regra do PRD: Apenas file.list se expressamente autorizada na missão
        if "file.list" in allowed_tools and workspace_path is not None and workspace_path.exists():
            target = workspace_path
            entries: list[str] = []
            for item in target.rglob("*"):
                try:
                    rel = item.relative_to(target)
                    if len(rel.parts) <= 4:
                        entries.append(str(rel).replace("\\", "/") + ("/" if item.is_dir() else ""))
                except ValueError:
                    continue

            sorted_entries = sorted(entries)[:1000]
            if sorted_entries:
                listing_str = "\n".join(sorted_entries)
                raw_observations.append(listing_str)
                evidence_refs.append("initial_environment_observation")

        normalized_obs = normalize_observations(raw_observations)

        payload = {
            "mission_id": mission_id,
            "seed": seed,
            "observations": normalized_obs,
            "allowed_tools": sorted(allowed_tools),
            "action_budget": list(action_budget) if action_budget is not None else None,
        }

        orientation_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

        return OrientationSnapshot(
            mission_id=mission_id,
            seed=seed,
            observations=normalized_obs,
            evidence_refs=evidence_refs,
            allowed_tools=sorted(allowed_tools),
            action_budget=action_budget,
            orientation_hash=orientation_hash,
        )
