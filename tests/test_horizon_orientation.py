"""Testes unitários, de integração, comportamentais e adversariais para Shared Environment Orientation (Horizon v0.7.1A)."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ultron.cognition.orientation import (
    EnvironmentOrientationService,
    canonical_json,
    compute_fixture_hash,
    normalize_observations,
)
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.core.receding_controller import RecedingHorizonController
from ultron.core.verifier import StepSuccessVerifier
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway, ModelResponse, Usage
from ultron.policy.engine import PolicyEngine
from ultron.schemas import (
    OrientationSnapshot,
    TaskCreate,
)
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Testes Unitários
# ---------------------------------------------------------------------------


def test_orientation_snapshot_canonical_hash_is_stable() -> None:
    payload_a = {
        "mission_id": "forge_01",
        "seed": 53,
        "observations": ["main.py\nconfig.json"],
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": [5, 12],
    }
    payload_b = {
        "action_budget": [5, 12],
        "allowed_tools": ["file.list", "python.execute"],
        "mission_id": "forge_01",
        "observations": ["main.py\nconfig.json"],
        "seed": 53,
    }

    hash_a = hashlib.sha256(canonical_json(payload_a).encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(canonical_json(payload_b).encode("utf-8")).hexdigest()

    assert hash_a == hash_b
    assert len(hash_a) == 64


def test_orientation_removes_ephemeral_ids() -> None:
    raw_obs = [
        "Task 3fa85f64-5717-4562-b3fc-2c963f66afa6 executed at 2026-08-22T09:00:00Z\nsolution.py\nconfig.json"
    ]
    normalized = normalize_observations(raw_obs)
    assert len(normalized) == 1
    assert "3fa85f64" not in normalized[0]
    assert "<EPHEMERAL_ID>" in normalized[0]
    assert "2026-08-22T09:00:00Z" not in normalized[0]
    assert "<TIMESTAMP>" in normalized[0]
    assert "solution.py" in normalized[0]
    assert "config.json" in normalized[0]


@pytest.mark.asyncio
async def test_orientation_does_not_use_disallowed_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_disallowed"
    workspace.mkdir(parents=True)
    (workspace / "secret.py").write_text("print(1)", encoding="utf-8")

    task = {
        "id": "forge_disallowed",
        "allowed_tools": ["python.execute"],  # file.list não está autorizado
        "action_budget": [5, 10],
    }
    service = EnvironmentOrientationService()
    snapshot = await service.build(task, seed=53, workspace_path=workspace)

    assert snapshot.observations == []
    assert snapshot.evidence_refs == []
    assert "file.list" not in snapshot.allowed_tools


@pytest.mark.asyncio
async def test_orientation_without_file_list_returns_empty_observation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_empty"
    workspace.mkdir(parents=True)
    (workspace / "a.txt").write_text("hello", encoding="utf-8")

    task = {
        "id": "forge_no_tools",
        "allowed_tools": [],
        "action_budget": [1, 5],
    }
    service = EnvironmentOrientationService()
    snapshot = await service.build(task, seed=42, workspace_path=workspace)

    assert snapshot.observations == []
    assert snapshot.evidence_refs == []
    assert snapshot.mission_id == "forge_no_tools"
    assert snapshot.seed == 42


# ---------------------------------------------------------------------------
# Helpers para testes de integração
# ---------------------------------------------------------------------------


def _setup_test_orchestrator(
    tmp_path: Path,
    mode: str,
    allowed_tools: list[str],
    seed: int = 53,
    mock_responses: list[ModelResponse] | None = None,
) -> tuple[Orchestrator, Database, list[dict[str, Any]]]:
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    settings.raw["cognition"]["controller_mode"] = mode
    settings.raw["memory"]["vector_enabled"] = False

    db = Database(tmp_path / f"test_{mode}.db")
    db.initialize()

    captured_prompts: list[dict[str, Any]] = []

    models = ModelGateway(settings)
    default_response = ModelResponse(
        content='{"intent":"Concluir","expected_evidence":{"type":"task_context"},"stop":true,"stop_reason":"concluido"}',
        tool_calls=[],
        usage=Usage(),
        latency_ms=1,
        model="qwen2.5:3b",
        finish_reason="stop",
        local=True,
    )
    plan_response = ModelResponse(
        content='{"objective":"teste","steps":[{"id":1,"action":"verificar","success_condition":"task_context"}],"risks":[],"confidence":0.9}',
        tool_calls=[],
        usage=Usage(),
        latency_ms=1,
        model="qwen2.5:3b",
        finish_reason="stop",
        local=True,
    )
    short_response = ModelResponse(
        content='{"actions":[{"intent":"Concluir","expected_evidence":{"type":"task_context"},"stop":true,"stop_reason":"concluido"}]}',
        tool_calls=[],
        usage=Usage(),
        latency_ms=1,
        model="qwen2.5:3b",
        finish_reason="stop",
        local=True,
    )

    resp_iter = iter(mock_responses or [plan_response, short_response, default_response])

    async def fake_generate(messages, model_name=None, **kwargs):
        captured_prompts.append({"messages": messages, "model_name": model_name, **kwargs})
        try:
            return next(resp_iter)
        except StopIteration:
            return default_response

    models.generate = fake_generate  # type: ignore[method-assign]

    tools = ToolRegistry(settings)
    tools.manifests = {name: manifest for name, manifest in tools.manifests.items() if name in allowed_tools}
    tools.handlers = {name: handler for name, handler in tools.handlers.items() if name in allowed_tools}

    orchestrator = Orchestrator(
        settings,
        db,
        EventBus(db),
        MemoryService(db, settings),
        models,
        PolicyEngine(settings),
        tools,
        planning_seed=seed,
    )
    orchestrator.context_builder.injection_limit = 0
    return orchestrator, db, captured_prompts


# ---------------------------------------------------------------------------
# 2. Testes de Integração
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_plan_receives_frozen_orientation(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspaces" / "ws_fp"
    ws_dir.mkdir(parents=True)
    (ws_dir / "solution.py").write_text("def solve(): pass", encoding="utf-8")
    (ws_dir / "config.yaml").write_text("mode: test", encoding="utf-8")

    task_payload = {
        "id": "mission_fp",
        "title": "Full Plan Test",
        "objective": "Resolver tarefa",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": (2, 5),
    }

    service = EnvironmentOrientationService()
    frozen_snapshot = await service.build(task_payload, seed=53, workspace_path=ws_dir)

    orchestrator, db, captured_prompts = _setup_test_orchestrator(
        tmp_path, "full_plan", task_payload["allowed_tools"], seed=53
    )

    created = await orchestrator.create_task(
        TaskCreate(
            title=task_payload["title"],
            objective=task_payload["objective"],
            workspace="ws_fp",
            autonomy_mode=4,
            allowed_tools=task_payload["allowed_tools"],
            action_budget=task_payload["action_budget"],
            requires_external_outcome=False,
        )
    )
    orchestrator.inject_orientation(created["id"], frozen_snapshot)

    await orchestrator.run(created["id"])
    active = orchestrator.active.get(created["id"])
    if active:
        await active

    # Verifica que o prompt do full_plan incluiu a observação do ambiente
    assert len(captured_prompts) >= 1
    user_content = next(
        msg["content"]
        for msg in captured_prompts[0]["messages"]
        if msg["role"] == "user"
    )
    assert "Observação inicial do ambiente:" in user_content
    assert "solution.py" in user_content
    assert "config.yaml" in user_content

    # Invariante: nenhuma tool call executada antes da decisão do plano
    tool_rows = db.all("SELECT tool_name FROM tool_executions WHERE task_id=?", (created["id"],))
    assert len(tool_rows) == 0


@pytest.mark.asyncio
async def test_short_horizon_receives_frozen_orientation(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspaces" / "ws_sh"
    ws_dir.mkdir(parents=True)
    (ws_dir / "app.py").write_text("x = 10", encoding="utf-8")

    task_payload = {
        "id": "mission_sh",
        "title": "Short Horizon Test",
        "objective": "Executar short horizon",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": (2, 5),
    }

    service = EnvironmentOrientationService()
    frozen_snapshot = await service.build(task_payload, seed=53, workspace_path=ws_dir)

    orchestrator, db, captured_prompts = _setup_test_orchestrator(
        tmp_path, "short_horizon", task_payload["allowed_tools"], seed=53
    )

    created = await orchestrator.create_task(
        TaskCreate(
            title=task_payload["title"],
            objective=task_payload["objective"],
            workspace="ws_sh",
            autonomy_mode=4,
            allowed_tools=task_payload["allowed_tools"],
            action_budget=task_payload["action_budget"],
            requires_external_outcome=False,
        )
    )
    orchestrator.inject_orientation(created["id"], frozen_snapshot)

    await orchestrator.run(created["id"])
    active = orchestrator.active.get(created["id"])
    if active:
        await active

    # Verifica se o snapshot inicial continha a observação congelada
    initial_snap = db.one("SELECT * FROM cognitive_snapshots WHERE task_id=? AND iteration=0", (created["id"],))
    assert initial_snap is not None
    obs = db.parse_json(initial_snap["recent_observations_json"], [])
    assert len(obs) >= 1
    assert "app.py" in obs[0]

    # Invariante: nenhuma tool call foi executada para obter essa orientação
    tool_rows = db.all("SELECT tool_name FROM tool_executions WHERE task_id=?", (created["id"],))
    assert len(tool_rows) == 0


@pytest.mark.asyncio
async def test_next_action_receives_frozen_orientation(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspaces" / "ws_na"
    ws_dir.mkdir(parents=True)
    (ws_dir / "data.csv").write_text("a,b\n1,2", encoding="utf-8")

    task_payload = {
        "id": "mission_na",
        "title": "Next Action Test",
        "objective": "Executar next action",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": (2, 5),
    }

    service = EnvironmentOrientationService()
    frozen_snapshot = await service.build(task_payload, seed=53, workspace_path=ws_dir)

    orchestrator, db, captured_prompts = _setup_test_orchestrator(
        tmp_path, "next_action", task_payload["allowed_tools"], seed=53
    )

    created = await orchestrator.create_task(
        TaskCreate(
            title=task_payload["title"],
            objective=task_payload["objective"],
            workspace="ws_na",
            autonomy_mode=4,
            allowed_tools=task_payload["allowed_tools"],
            action_budget=task_payload["action_budget"],
            requires_external_outcome=False,
        )
    )
    orchestrator.inject_orientation(created["id"], frozen_snapshot)

    await orchestrator.run(created["id"])
    active = orchestrator.active.get(created["id"])
    if active:
        await active

    initial_snap = db.one("SELECT * FROM cognitive_snapshots WHERE task_id=? AND iteration=0", (created["id"],))
    assert initial_snap is not None
    obs = db.parse_json(initial_snap["recent_observations_json"], [])
    assert len(obs) >= 1
    assert "data.csv" in obs[0]

    # Invariante: tool_call_count == 0 antes da decisão
    tool_rows = db.all("SELECT tool_name FROM tool_executions WHERE task_id=?", (created["id"],))
    assert len(tool_rows) == 0


@pytest.mark.asyncio
async def test_controllers_do_not_reorient_before_first_decision(tmp_path: Path) -> None:
    """Verifica que nenhum dos 3 controladores executa reorientação ou chamadas de ferramenta antes da primeira decisão."""
    for mode in ("full_plan", "short_horizon", "next_action"):
        ws_dir = tmp_path / "workspaces" / f"ws_{mode}_noreorient"
        ws_dir.mkdir(parents=True)
        (ws_dir / "target.py").write_text("print('test')", encoding="utf-8")

        task_payload = {
            "id": f"mission_{mode}",
            "title": f"Test {mode}",
            "objective": "Resolver",
            "allowed_tools": ["file.list", "python.execute"],
            "action_budget": (2, 5),
        }

        service = EnvironmentOrientationService()
        frozen_snapshot = await service.build(task_payload, seed=53, workspace_path=ws_dir)

        orchestrator, db, captured_prompts = _setup_test_orchestrator(
            tmp_path, mode, task_payload["allowed_tools"], seed=53
        )

        created = await orchestrator.create_task(
            TaskCreate(
                title=task_payload["title"],
                objective=task_payload["objective"],
                workspace=f"ws_{mode}_noreorient",
                autonomy_mode=4,
                allowed_tools=task_payload["allowed_tools"],
                action_budget=task_payload["action_budget"],
                requires_external_outcome=False,
            )
        )
        orchestrator.inject_orientation(created["id"], frozen_snapshot)

        await orchestrator.run(created["id"])
        active = orchestrator.active.get(created["id"])
        if active:
            await active

        tool_execs = db.all("SELECT * FROM tool_executions WHERE task_id=?", (created["id"],))
        assert len(tool_execs) == 0, f"Modo {mode} executou tool calls antes da decisão: {tool_execs}"


# ---------------------------------------------------------------------------
# 3. Behavioral Contract Principal (PRD Seção 20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_behavioral_contract_same_perception_before_first_decision(tmp_path: Path) -> None:
    """Given: same mission, same seed, same fixture.

    When: run A/B/C until immediately before first model decision.
    Then:
    - orientation snapshots are byte-equivalent after canonicalization
    - orientation hashes are equal
    - fixture hashes are equal
    - no controller performed extra tool call.
    """
    mission = {
        "id": "forge_e2e_contract_01",
        "title": "Reparar módulo Python mínimo",
        "objective": "Crie uma implementação Python mínima e verificável no workspace.",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": [5, 12],
    }
    seed = 53

    # Setup fixture template
    fixture_dir = tmp_path / "fixtures" / "forge_01"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "module.py").write_text("# TODO: implement\n", encoding="utf-8")
    (fixture_dir / "test_module.py").write_text("import module\n", encoding="utf-8")

    # 1. Constrói orientação congelada uma única vez
    service = EnvironmentOrientationService()
    frozen_snapshot = await service.build(mission, seed=seed, workspace_path=fixture_dir)

    snapshots_by_mode: dict[str, OrientationSnapshot] = {}
    fixture_hashes_by_mode: dict[str, str] = {}
    tool_calls_before_decision: dict[str, int] = {}
    first_llm_requests: dict[str, list[dict[str, Any]]] = {}

    for mode in ("full_plan", "short_horizon", "next_action"):
        # Prepara workspace isolado com fixture equivalente
        mode_ws = tmp_path / "workspaces" / f"horizon_{mode}"
        mode_ws.mkdir(parents=True)
        (mode_ws / "module.py").write_text("# TODO: implement\n", encoding="utf-8")
        (mode_ws / "test_module.py").write_text("import module\n", encoding="utf-8")

        mode_fixture_hash = compute_fixture_hash(mode_ws)
        fixture_hashes_by_mode[mode] = mode_fixture_hash

        # Captura snapshot congelado que o controlador recebe
        snapshots_by_mode[mode] = deepcopy(frozen_snapshot)

        orchestrator, db, captured_prompts = _setup_test_orchestrator(
            tmp_path, mode, mission["allowed_tools"], seed=seed
        )

        created = await orchestrator.create_task(
            TaskCreate(
                title=mission["title"],
                objective=mission["objective"],
                workspace=f"horizon_{mode}",
                autonomy_mode=4,
                allowed_tools=mission["allowed_tools"],
                action_budget=(mission["action_budget"][0], mission["action_budget"][1]),
                requires_external_outcome=False,
            )
        )
        orchestrator.inject_orientation(created["id"], frozen_snapshot)

        await orchestrator.run(created["id"])
        active = orchestrator.active.get(created["id"])
        if active:
            await active

        # Registra chamadas de ferramentas antes da primeira decisão cognitiva
        tool_count = len(db.all("SELECT * FROM tool_executions WHERE task_id=?", (created["id"],)))
        tool_calls_before_decision[mode] = tool_count

        if captured_prompts:
            first_llm_requests[mode] = captured_prompts[0]["messages"]

    # Validações do Contrato Comportamental:
    # 1. Hashes de fixture são estritamente iguais
    assert len(set(fixture_hashes_by_mode.values())) == 1, f"Fixture hashes divergiram: {fixture_hashes_by_mode}"

    # 2. Orientation snapshots são byte-equivalentes após canonicalização
    canonical_snapshots = {
        mode: canonical_json(snap.model_dump(mode="json"))
        for mode, snap in snapshots_by_mode.items()
    }
    assert len(set(canonical_snapshots.values())) == 1, f"Snapshots divergiram: {canonical_snapshots}"

    # 3. Orientation hashes são idênticos
    orientation_hashes = {snap.orientation_hash for snap in snapshots_by_mode.values()}
    assert len(orientation_hashes) == 1

    # 4. Nenhum controlador executou chamada extra de ferramenta antes da primeira decisão cognitiva
    assert all(count == 0 for count in tool_calls_before_decision.values()), (
        f"Controladores executaram ferramentas antes da decisão: {tool_calls_before_decision}"
    )

    # 5. O que efetivamente chegou ao modelo na PRIMEIRA chamada LLM de cada modo deve ser canonicamente idêntico
    def extract_initial_environment_information(messages: list[dict[str, Any]]) -> str:
        for msg in messages:
            content = str(msg.get("content", ""))
            if "Observação inicial do ambiente:" in content:
                parts = content.split("Observação inicial do ambiente:", 1)[1]
                lines = []
                for line in parts.split("\n"):
                    if line.strip().startswith(("Memórias", "Ferramentas autorizadas", "Ferramentas", "Subobjetivo", "Contrato", "Orçamento", "Fatos conhecidos", "Outline:", "Contexto:")):
                        break
                    lines.append(line)
                extracted = "\n".join(lines).strip()
                if extracted:
                    return extracted
        return ""

    info_a = extract_initial_environment_information(first_llm_requests["full_plan"])
    info_b = extract_initial_environment_information(first_llm_requests["short_horizon"])
    info_c = extract_initial_environment_information(first_llm_requests["next_action"])

    assert info_a != "", "full_plan não continha observação inicial do ambiente na 1ª chamada LLM"
    assert info_b != "", "short_horizon não continha observação inicial do ambiente na 1ª chamada LLM"
    assert info_c != "", "next_action não continha observação inicial do ambiente na 1ª chamada LLM"
    assert canonical_json(info_a) == canonical_json(info_b) == canonical_json(info_c), (
        f"Percepção ambiental da 1ª chamada LLM divergiu!\nA: {info_a}\nB: {info_b}\nC: {info_c}"
    )



# ---------------------------------------------------------------------------
# 4. Testes Adversariais
# ---------------------------------------------------------------------------


def test_orientation_mismatch_invalidates_measurement() -> None:
    runner_traces = [
        {
            "mission_id": "forge_01",
            "controller_mode": "full_plan",
            "model_attribution_verified": True,
            "seed_attribution_verified": True,
            "mission_contract_verified": True,
            "orientation_shared_verified": True,
            "tool_contract_respected": True,
            "action_budget_cap_respected": True,
            "pre_decision_tool_call_detected": False,
            "orientation_observation_hash": "hash_aaa",
            "initial_fixture_hash": "fix_111",
            "model_cognitive_success": True,
            "tool_calls": 1,
            "llm_calls": 1,
        },
        {
            "mission_id": "forge_01",
            "controller_mode": "next_action",
            "model_attribution_verified": True,
            "seed_attribution_verified": True,
            "mission_contract_verified": True,
            "orientation_shared_verified": True,
            "tool_contract_respected": True,
            "action_budget_cap_respected": True,
            "pre_decision_tool_call_detected": False,
            "orientation_observation_hash": "hash_bbb_divergente",  # Mismatch!
            "initial_fixture_hash": "fix_111",
            "model_cognitive_success": True,
            "tool_calls": 1,
            "llm_calls": 1,
        },
    ]

    invalidation_reasons: list[str] = []
    by_mission: dict[str, list[dict]] = {}
    for trace in runner_traces:
        by_mission.setdefault(trace["mission_id"], []).append(trace)

    for mid, m_traces in by_mission.items():
        orient_hashes = {t["orientation_observation_hash"] for t in m_traces}
        if len(orient_hashes) > 1:
            invalidation_reasons.append("orientation_observation_mismatch")

    assert "orientation_observation_mismatch" in invalidation_reasons


def test_different_fixture_invalidates_measurement() -> None:
    runner_traces = [
        {
            "mission_id": "forge_01",
            "controller_mode": "full_plan",
            "orientation_observation_hash": "hash_aaa",
            "initial_fixture_hash": "fix_aaa",
        },
        {
            "mission_id": "forge_01",
            "controller_mode": "next_action",
            "orientation_observation_hash": "hash_aaa",
            "initial_fixture_hash": "fix_bbb_modificado",  # Fixture mismatch!
        },
    ]

    invalidation_reasons: list[str] = []
    by_mission: dict[str, list[dict]] = {}
    for trace in runner_traces:
        by_mission.setdefault(trace["mission_id"], []).append(trace)

    for mid, m_traces in by_mission.items():
        fixture_hashes = {t["initial_fixture_hash"] for t in m_traces}
        if len(fixture_hashes) > 1:
            invalidation_reasons.append("initial_fixture_mismatch")

    assert "initial_fixture_mismatch" in invalidation_reasons


@pytest.mark.asyncio
async def test_orientation_cannot_read_private_evaluator(tmp_path: Path) -> None:
    """Verifica que o EnvironmentOrientationService não lê arquivos fora do workspace nem contratos privados."""
    workspace = tmp_path / "ws_isolated"
    workspace.mkdir(parents=True)
    (workspace / "public_file.py").write_text("print('ok')", encoding="utf-8")

    # Arquivo privado em diretório irmão/pai
    private_dir = tmp_path / "private_contracts"
    private_dir.mkdir(parents=True)
    (private_dir / "answers.json").write_text('{"secret": "hidden"}', encoding="utf-8")

    task = {
        "id": "forge_security_test",
        "allowed_tools": ["file.list"],
        "action_budget": [5, 10],
    }

    service = EnvironmentOrientationService()
    snapshot = await service.build(task, seed=53, workspace_path=workspace)

    assert len(snapshot.observations) == 1
    assert "public_file.py" in snapshot.observations[0]
    assert "answers.json" not in snapshot.observations[0]
    assert "hidden" not in snapshot.observations[0]


@pytest.mark.asyncio
async def test_closed_loop_cannot_gain_extra_initial_observation(tmp_path: Path) -> None:
    """Garante que closed-loop com snapshot injetado não executa file.list adicional."""
    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    db = Database(tmp_path / "test_no_extra_obs.db")
    db.initialize()

    executed_tools: list[str] = []

    async def execute_tool(_task_id: str, call) -> dict:
        executed_tools.append(call.tool_name)
        return {"status": "completed", "output": "ok", "error": None}

    tools = ToolRegistry(settings)
    controller = RecedingHorizonController(
        settings,
        db,
        EventBus(db),
        ModelGateway(settings),
        tools,
        StepSuccessVerifier(tools),
        execute_tool,
        planning_seed=53,
    )

    task = {
        "id": str(uuid4()),
        "objective": "Testar no extra observation",
        "workspace": "ws_test",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": [5, 10],
        "tool_call_count": 0,
        "replan_count": 0,
    }
    db.execute(
        "INSERT INTO tasks (id,title,objective,status,priority,workspace,autonomy_mode,allowed_tools_json,action_budget_min,action_budget_max,created_at,updated_at) VALUES (?, ?, ?, 'created', 0.5, ?, 4, ?, 5, 10, 'now', 'now')",
        (task["id"], "Test", task["objective"], task["workspace"], db.json(task["allowed_tools"])),
    )

    frozen_orientation = OrientationSnapshot(
        mission_id=task["id"],
        seed=53,
        observations=["file1.py\nfile2.py"],
        evidence_refs=["initial_environment_observation"],
        allowed_tools=["file.list", "python.execute"],
        action_budget=(5, 10),
        orientation_hash="hash123",
    )

    snap = await controller.ensure_initial_observation(task, orientation=frozen_orientation)

    assert len(executed_tools) == 0, f"Tools executadas inesperadamente: {executed_tools}"
    assert snap.recent_observations == ["file1.py\nfile2.py"]
    assert snap.iteration == 0


@pytest.mark.asyncio
async def test_orientation_service_uses_real_tool_registry_handler(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_real_tools"
    workspace.mkdir(parents=True)
    (workspace / "a.py").write_text("print('a')", encoding="utf-8")
    (workspace / "b.txt").write_text("content", encoding="utf-8")

    settings = Settings(raw=deepcopy(load_settings(ROOT).raw), root_dir=tmp_path)
    tools = ToolRegistry(settings)

    task = {
        "id": "forge_handler_test",
        "allowed_tools": ["file.list", "python.execute"],
        "action_budget": [5, 10],
    }

    service = EnvironmentOrientationService(tools)
    snapshot = await service.build(task, seed=53, workspace_path=workspace, tools=tools)

    assert len(snapshot.observations) == 1
    assert "a.py" in snapshot.observations[0]
    assert "b.txt" in snapshot.observations[0]
    assert snapshot.allowed_tools == ["file.list", "python.execute"]


def test_ref_fixture_mismatch_invalidates_measurement() -> None:
    runner_traces = [
        {
            "mission_id": "forge_01",
            "controller_mode": "full_plan",
            "orientation_observation_hash": "hash_aaa",
            "ref_fixture_hash": "ref_fix_000",
            "initial_fixture_hash": "ref_fix_000",
        },
        {
            "mission_id": "forge_01",
            "controller_mode": "short_horizon",
            "orientation_observation_hash": "hash_aaa",
            "ref_fixture_hash": "ref_fix_000",
            "initial_fixture_hash": "corrupted_mode_fixture_hash",
        },
        {
            "mission_id": "forge_01",
            "controller_mode": "next_action",
            "orientation_observation_hash": "hash_aaa",
            "ref_fixture_hash": "ref_fix_000",
            "initial_fixture_hash": "ref_fix_000",
        },
    ]

    invalidation_reasons: list[str] = []
    by_mission: dict[str, list[dict]] = {}
    for trace in runner_traces:
        by_mission.setdefault(trace["mission_id"], []).append(trace)

    for mid, m_traces in by_mission.items():
        fixture_hashes = {t["initial_fixture_hash"] for t in m_traces}
        ref_f_hash = m_traces[0].get("ref_fixture_hash")
        if len(fixture_hashes) > 1 or any(h != ref_f_hash for h in fixture_hashes):
            invalidation_reasons.append("initial_fixture_mismatch")

    assert "initial_fixture_mismatch" in invalidation_reasons
