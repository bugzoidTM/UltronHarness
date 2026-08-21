from __future__ import annotations

import asyncio

from ultron.cognition.task_signature import TaskSignatureClassifier
from ultron.models.gateway import ModelResponse, Usage


def test_unknown_task_abstains() -> None:
    signature = TaskSignatureClassifier.classify({"objective": "Organize ideias abstratas sem ferramenta ou domínio definido."})
    assert signature.family == "unknown"
    assert signature.classification_source == "abstain"
    assert signature.uncertainty == 1.0


def test_explicit_metadata_uses_closed_family_set() -> None:
    signature = TaskSignatureClassifier.classify({"family": "invented_family", "objective": "Caso qualquer"})
    assert signature.family == "unknown"
    assert signature.classification_source == "explicit_metadata_rejected"


def test_llm_classifier_cannot_invent_family() -> None:
    class Gateway:
        async def generate(self, *_args, **_kwargs):
            return ModelResponse('{"family":"novel_label","confidence":0.99}', [], Usage(), 0, "test", "stop", True)

    signature = asyncio.run(TaskSignatureClassifier.classify_with_model({"objective": "Caso sem pistas"}, Gateway(), "local-fallback"))
    assert signature.family == "unknown"
    assert signature.classification_source == "structured_classifier_abstain"


def test_structured_classifier_requires_confidence_gate() -> None:
    signature = TaskSignatureClassifier.from_structured(
        {"objective": "Caso sem pistas"},
        {"family": "planning", "confidence": 0.74},
    )
    assert signature.family == "unknown"
