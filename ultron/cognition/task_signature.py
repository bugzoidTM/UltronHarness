"""Assinatura pública, determinística e auditável de tarefas para o Project Hermes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ultron.db import Database


class TaskSignature(BaseModel):
    category: str = "unknown"
    family: str = "unknown"
    domain: str = "unknown"
    required_tools: list[str] = Field(default_factory=list)
    failure_class: str | None = None
    artifact_type: str | None = None
    operation_kind: str | None = None
    difficulty: str | None = None
    uncertainty: float = Field(default=1.0, ge=0.0, le=1.0)
    classification_source: str = "abstain"


class TaskSignatureClassifier:
    """Classifica sem consultar respostas, avaliadores privados ou um LLM livre."""

    _FAMILY_HINTS = {
        "dependency_recovery": ("depend", "import", "require", "package", "manifest"),
        "structured_validation": ("schema", "json", "yaml", "campo", "field", "valid"),
        "state_recovery": ("restore", "revert", "state", "recover", "rollback"),
        "planning": ("plan", "dependen", "precondition", "prerequisite", "workflow"),
        "configuration_repair": ("config", "setting", "environment", "option"),
    }

    @classmethod
    def classify(cls, task: dict[str, Any]) -> TaskSignature:
        explicit_family = str(task.get("family") or "").strip()
        explicit_category = str(task.get("category") or "").strip()
        explicit_domain = str(task.get("target_domain") or task.get("domain") or "").strip()
        required_tools = list(task.get("allowed_tools") or task.get("required_tools") or [])
        if explicit_family and explicit_category:
            return TaskSignature(
                category=explicit_category,
                family=explicit_family,
                domain=explicit_domain or "unknown",
                required_tools=required_tools,
                failure_class=task.get("failure_class"),
                artifact_type=task.get("artifact_type"),
                operation_kind=task.get("operation_kind"),
                difficulty=task.get("difficulty"),
                uncertainty=0.0,
                classification_source="explicit_public_metadata",
            )
        text = " ".join(str(task.get(key, "")) for key in ("objective", "title", "workspace_fixture")).lower()
        matched = [family for family, hints in cls._FAMILY_HINTS.items() if any(hint in text for hint in hints)]
        if len(matched) != 1:
            return TaskSignature(
                category=explicit_category or "unknown",
                family="unknown",
                domain=explicit_domain or "unknown",
                required_tools=required_tools,
                difficulty=task.get("difficulty"),
                uncertainty=1.0,
                classification_source="abstain",
            )
        family = matched[0]
        category = explicit_category or ("recovery" if family in {"dependency_recovery", "state_recovery"} else "reasoning")
        return TaskSignature(
            category=category,
            family=family,
            domain=explicit_domain or "unknown",
            required_tools=required_tools,
            failure_class=task.get("failure_class"),
            artifact_type=task.get("artifact_type"),
            operation_kind=task.get("operation_kind"),
            difficulty=task.get("difficulty"),
            uncertainty=0.25,
            classification_source="deterministic_heuristic",
        )

    @staticmethod
    def persist(db: Database, signature: TaskSignature, task_id: str | None = None) -> str:
        signature_id = str(uuid4())
        db.execute(
            "INSERT INTO task_signatures (id,task_id,category,family,domain,required_tools_json,failure_class,artifact_type,operation_kind,difficulty,uncertainty,source,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                signature_id,
                task_id,
                signature.category,
                signature.family,
                signature.domain,
                db.json(signature.required_tools),
                signature.failure_class,
                signature.artifact_type,
                signature.operation_kind,
                signature.difficulty,
                signature.uncertainty,
                signature.classification_source,
                datetime.now(UTC).isoformat(),
            ),
        )
        return signature_id
