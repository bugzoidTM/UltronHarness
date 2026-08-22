"""Assinaturas de experiências procedurais, sem inferência subjetiva por modelo."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ultron.db import Database


class ExperienceSignature(BaseModel):
    category: str = "unknown"
    family: str = "unknown"
    domain: str = "unknown"
    applicable_failure_classes: list[str] = Field(default_factory=list)
    tool_families: list[str] = Field(default_factory=list)
    abstraction_level: float = Field(default=0.5, ge=0.0, le=1.0)
    verified: bool = False
    historical_utility: float = Field(default=0.0, ge=-1.0, le=1.0)
    sample_count: int = Field(default=0, ge=0)
    source: str = "deterministic_metadata"


class ExperienceSignatureBuilder:
    """Produz assinatura somente de metadados, evidência e resultados observados."""

    @staticmethod
    def build(experience: dict[str, Any], *, utility: float = 0.0, sample_count: int = 0) -> ExperienceSignature:
        metadata = experience.get("metadata") if isinstance(experience.get("metadata"), dict) else {}
        family = str(metadata.get("family") or experience.get("family") or "unknown")
        category = str(metadata.get("category") or experience.get("category") or "unknown")
        domain = str(metadata.get("domain") or experience.get("domain") or "unknown")
        failures = list(metadata.get("applicable_failure_classes") or experience.get("applicable_failure_classes") or [])
        tools = list(metadata.get("tool_families") or experience.get("tool_families") or [])
        abstraction = float(metadata.get("abstraction_level", experience.get("abstraction_level", 0.5)))
        verified = bool(metadata.get("verified", experience.get("verified", False)))
        return ExperienceSignature(
            category=category,
            family=family,
            domain=domain,
            applicable_failure_classes=failures,
            tool_families=tools,
            abstraction_level=min(1.0, max(0.0, abstraction)),
            verified=verified,
            historical_utility=min(1.0, max(-1.0, utility)),
            sample_count=max(0, sample_count),
        )

    @staticmethod
    def persist(db: Database, signature: ExperienceSignature, experience_id: str) -> str:
        if signature.verified:
            audit = db.one(
                "SELECT id FROM verified_writebacks WHERE target_type='experience' AND target_id=? AND allowed=1 ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (experience_id,),
            )
            if not audit:
                raise ValueError("Assinatura verificada exige verified writeback autorizado para a experiência.")
        signature_id = str(uuid4())
        db.execute(
            "INSERT INTO experience_signatures (id,experience_id,category,family,domain,failure_classes_json,tool_families_json,abstraction_level,verified,historical_utility,sample_count,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                signature_id,
                experience_id,
                signature.category,
                signature.family,
                signature.domain,
                db.json(signature.applicable_failure_classes),
                db.json(signature.tool_families),
                signature.abstraction_level,
                int(signature.verified),
                signature.historical_utility,
                signature.sample_count,
                signature.source,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        return signature_id
