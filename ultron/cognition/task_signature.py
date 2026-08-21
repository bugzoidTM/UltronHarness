"""Task Signature v2: metadados, heurística determinística e fallback estruturado seguro."""

from __future__ import annotations

import json
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
    """Nunca permite que uma classificação incerta habilite injeção de contexto."""

    ALLOWED_FAMILIES = {
        "structured_validation",
        "dependency_recovery",
        "state_recovery",
        "planning",
        "configuration_repair",
        "unknown",
    }
    CONFIDENCE_GATE = 0.75
    _FAMILY_HINTS = {
        "dependency_recovery": ("depend", "import", "require", "package", "manifest"),
        "structured_validation": ("schema", "json", "yaml", "campo", "field", "valid"),
        "state_recovery": ("restore", "revert", "state", "recover", "rollback"),
        "planning": ("plan", "dependen", "precondition", "prerequisite", "workflow"),
        "configuration_repair": ("config", "setting", "environment", "option"),
    }

    @classmethod
    def _unknown(cls, task: dict[str, Any], source: str = "abstain") -> TaskSignature:
        return TaskSignature(
            category=str(task.get("category") or "unknown"),
            family="unknown",
            domain=str(task.get("target_domain") or task.get("domain") or "unknown"),
            required_tools=list(task.get("allowed_tools") or task.get("required_tools") or []),
            difficulty=task.get("difficulty"),
            uncertainty=1.0,
            classification_source=source,
        )

    @classmethod
    def _category(cls, family: str, explicit: str = "") -> str:
        return explicit or ("recovery" if family in {"dependency_recovery", "state_recovery"} else "reasoning")

    @classmethod
    def classify(cls, task: dict[str, Any]) -> TaskSignature:
        explicit_family = str(task.get("family") or "").strip()
        explicit_category = str(task.get("category") or "").strip()
        explicit_domain = str(task.get("target_domain") or task.get("domain") or "").strip()
        required_tools = list(task.get("allowed_tools") or task.get("required_tools") or [])
        if explicit_family:
            if explicit_family not in cls.ALLOWED_FAMILIES or explicit_family == "unknown":
                return cls._unknown(task, "explicit_metadata_rejected")
            return TaskSignature(
                category=cls._category(explicit_family, explicit_category),
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
            return cls._unknown(task)
        family = matched[0]
        return TaskSignature(
            category=cls._category(family, explicit_category),
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

    @classmethod
    def from_structured(cls, task: dict[str, Any], payload: dict[str, Any]) -> TaskSignature:
        """Valida uma saída estruturada; qualquer invenção ou baixa confiança abstém."""
        family = str(payload.get("family") or "unknown")
        confidence = float(payload.get("confidence") or 0.0)
        if family not in cls.ALLOWED_FAMILIES or family == "unknown" or confidence < cls.CONFIDENCE_GATE:
            return cls._unknown(task, "structured_classifier_abstain")
        category = str(payload.get("category") or cls._category(family))
        domain = str(payload.get("domain") or task.get("target_domain") or task.get("domain") or "unknown")
        return TaskSignature(
            category=category,
            family=family,
            domain=domain,
            required_tools=list(task.get("allowed_tools") or task.get("required_tools") or []),
            uncertainty=round(1.0 - confidence, 6),
            classification_source="structured_local_classifier",
        )

    @classmethod
    async def classify_with_model(cls, task: dict[str, Any], gateway: Any, model_name: str) -> TaskSignature:
        deterministic = cls.classify(task)
        if deterministic.family != "unknown":
            return deterministic
        schema_families = ", ".join(sorted(cls.ALLOWED_FAMILIES))
        messages = [
            {"role": "system", "content": f"Classifique a tarefa sem criar rótulos fora desta lista: {schema_families}. Responda somente JSON com category, family, domain, confidence e evidence."},
            {"role": "user", "content": json.dumps({"title": task.get("title"), "objective": task.get("objective"), "domain": task.get("target_domain") or task.get("domain")}, ensure_ascii=False)},
        ]
        try:
            response = await gateway.generate(messages, model_name, max_tokens=96, json_mode=True)
            payload = json.loads(response.content)
            return cls.from_structured(task, payload if isinstance(payload, dict) else {})
        except (ValueError, TypeError, json.JSONDecodeError):
            return cls._unknown(task, "structured_classifier_error")

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
