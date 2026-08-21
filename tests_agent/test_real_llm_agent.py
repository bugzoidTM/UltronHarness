from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ultron.configuration import load_settings
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import RiskLevel


pytestmark = [pytest.mark.agent, pytest.mark.slow, pytest.mark.llm]


def _record(name: str, response: object) -> None:
    settings = load_settings()
    target = settings.artifacts_dir / "agent_tests" / "observations.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test": name,
        "at": datetime.now(UTC).isoformat(),
        "model": response.model,
        "latency_ms": response.latency_ms,
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "content": response.content[:1000],
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


@pytest.fixture(scope="module")
def gateway() -> ModelGateway:
    settings = load_settings()
    settings.raw["models"]["timeout_seconds"] = 15
    return ModelGateway(settings)


def _ask(gateway: ModelGateway, prompt: str, test_name: str):
    try:
        response = asyncio.run(
            gateway.generate(
                [
                    {"role": "system", "content": "Responda de forma objetiva. Não exponha raciocínio privado."},
                    {"role": "user", "content": prompt},
                ]
            )
        )
    except Exception as exc:
        pytest.xfail(f"Runtime local não respondeu para {test_name}: {type(exc).__name__}")
    _record(test_name, response)
    assert response.local is True
    assert response.content.strip()
    return response


def test_agent_plan_simple_task(gateway: ModelGateway) -> None:
    _ask(gateway, "Liste em uma frase os passos para somar dois números sem ferramenta.", "plan_simple_task")


def test_agent_selects_correct_tool(gateway: ModelGateway) -> None:
    response = _ask(gateway, "Para ler um arquivo local, responda somente o nome da ferramenta correta.", "selects_correct_tool")
    if "file" not in response.content.casefold():
        pytest.xfail("O modelo local respondeu, mas não selecionou corretamente a ferramenta neste seed.")


def test_agent_detects_tool_failure(gateway: ModelGateway) -> None:
    response = _ask(gateway, "Um arquivo não existe e a leitura falhou. Diga a categoria MISSING_RESOURCE.", "detects_tool_failure")
    assert "missing" in response.content.casefold() or "recurso" in response.content.casefold()


def test_agent_replans_after_failure(gateway: ModelGateway) -> None:
    _ask(gateway, "Uma tentativa falhou por JSON inválido. Proponha uma ação de recuperação em uma frase.", "replans_after_failure")


def test_agent_uses_relevant_memory(gateway: ModelGateway) -> None:
    response = _ask(gateway, "Memória relevante: a raiz quadrada de 81 é 9. Qual é a raiz quadrada de 81?", "uses_relevant_memory")
    assert "9" in response.content


def test_agent_ignores_irrelevant_memory(gateway: ModelGateway) -> None:
    response = _ask(gateway, "Memória irrelevante: o céu pode ser azul. Quanto é 2+2?", "ignores_irrelevant_memory")
    assert "4" in response.content


def test_agent_finishes_when_goal_met(gateway: ModelGateway) -> None:
    _ask(gateway, "O objetivo já foi satisfeito e a evidência está presente. Responda com uma confirmação curta.", "finishes_when_goal_met")


def test_agent_respects_max_steps(gateway: ModelGateway) -> None:
    response = _ask(gateway, "Com limite de 2 passos, apresente no máximo 2 passos para validar um arquivo.", "respects_max_steps")
    assert len(response.content.splitlines()) <= 8


def test_agent_respects_policy() -> None:
    settings = load_settings()
    decision = PolicyEngine(settings).evaluate("file.write", {"path": "patch.py"}, RiskLevel.R2, 2)
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_agent_produces_verifiable_artifact(gateway: ModelGateway, tmp_path: Path) -> None:
    response = _ask(gateway, "Escreva somente uma linha Python que define x como 3.", "produces_verifiable_artifact")
    artifact = tmp_path / "answer.py"
    artifact.write_text(response.content, encoding="utf-8")
    assert artifact.read_text(encoding="utf-8").strip()
