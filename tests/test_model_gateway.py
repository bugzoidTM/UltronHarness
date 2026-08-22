from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ultron.configuration import Settings, load_settings
from ultron.models.gateway import ModelGateway, ModelResponse, Usage
from ultron.schemas import Plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_structured_repair_preserves_model_seed_and_observes_attempts(tmp_path: Path) -> None:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    gateway = ModelGateway(settings)
    calls: list[dict[str, object]] = []
    observed: list[tuple[str, bool]] = []
    responses = iter(
        [
            ModelResponse(
                content='{"objective":"reparo","steps":[{"id":0}]}',
                tool_calls=[],
                usage=Usage(),
                latency_ms=1,
                model="qwen2.5:3b",
                finish_reason="stop",
                local=True,
            ),
            ModelResponse(
                content=(
                    '{"objective":"reparo","steps":[{"id":1,"action":"Analisar contexto",'
                    '"success_condition":"task_context"}],"risks":[],"confidence":0.8}'
                ),
                tool_calls=[],
                usage=Usage(),
                latency_ms=2,
                model="qwen2.5:3b",
                finish_reason="stop",
                local=True,
            ),
        ]
    )

    async def fake_generate(messages, model_name=None, **kwargs):
        calls.append({"messages": messages, "model_name": model_name, **kwargs})
        return next(responses)

    async def observe(response: ModelResponse, is_repair: bool) -> None:
        observed.append((response.model, is_repair))

    gateway.generate = fake_generate  # type: ignore[method-assign]
    plan = await gateway.structured(
        Plan,
        [{"role": "user", "content": "gere um plano"}],
        model_name="ollama_research",
        seed=49,
        on_response=observe,
    )

    assert plan.confidence == 0.8
    assert [(call["model_name"], call["seed"], call["json_mode"]) for call in calls] == [
        ("ollama_research", 49, True),
        ("ollama_research", 49, True),
    ]
    assert observed == [("qwen2.5:3b", False), ("qwen2.5:3b", True)]
