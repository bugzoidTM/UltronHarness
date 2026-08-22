"""Benchmark E2E generativo Forge com avaliador privado como única fonte de sucesso."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import platform
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import uuid4

import yaml

from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import TaskCreate
from ultron.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ForgeE2EResult:
    run_id: str
    total: int
    passed: int
    atc: float
    artifact_dir: Path


def _load_private_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("forge_private_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Avaliador E2E privado indisponível")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForgeE2ERunner:
    def __init__(
        self,
        settings: Settings,
        *,
        public_root: Path | None = None,
        private_root: Path | None = None,
        model_name: str = "ollama_research",
        seed: int = 42,
    ):
        self.settings = Settings(raw=deepcopy(settings.raw), root_dir=settings.root_dir)
        self.public_root = public_root or self.settings.root_dir / "benchmarks" / "forge_e2e_v1"
        configured = private_root or self.settings.private_benchmark_root
        if configured is None:
            raise FileNotFoundError("Forge E2E exige raiz privada externa configurada.")
        self.private_root = configured / "forge_e2e_v1" if not (configured / "contracts.json").exists() else configured
        if model_name not in self.settings.raw["models"]["registry"]:
            raise ValueError(f"Modelo Forge não registrado: {model_name}")
        self.model_name, self.seed = model_name, seed
        # O Orchestrator chama ModelGateway.generate() sem model_name. Fixar o
        # primário nesta cópia é a única forma de tornar --model efetivo.
        self.settings.raw["models"]["primary"] = self.model_name
        self.configured_model = str(self.settings.raw["models"]["registry"][self.model_name].get("model", self.model_name))
        self.settings.raw["models"]["timeout_seconds"] = max(300, int(self.settings.raw["models"].get("timeout_seconds", 120)))
        self.db = Database(settings.db_path)
        self.db.initialize()

    def _tasks(self) -> list[dict]:
        payload = yaml.safe_load((self.public_root / "tasks.yaml").read_text(encoding="utf-8")) or []
        if not isinstance(payload, list) or len(payload) != 10:
            raise ValueError("Forge E2E v1 exige dez missões públicas")
        return payload

    def _orchestrator(self, allowed_tools: list[str]) -> Orchestrator:
        models = ModelGateway(self.settings)
        tools = ToolRegistry(self.settings)
        allowed = set(allowed_tools)
        unavailable = allowed.difference(tools.manifests)
        if unavailable:
            raise ValueError(f"Ferramentas E2E não registradas: {sorted(unavailable)}")
        tools.manifests = {name: manifest for name, manifest in tools.manifests.items() if name in allowed}
        tools.handlers = {name: handler for name, handler in tools.handlers.items() if name in allowed}
        return Orchestrator(
            self.settings,
            self.db,
            EventBus(self.db),
            MemoryService(self.db, self.settings),
            models,
            PolicyEngine(self.settings),
            tools,
        )

    @staticmethod
    def _failure_taxonomy(db: Database, task_id: str) -> dict[str, int]:
        categories = {"plan": 0, "tool": 0, "argument": 0, "verification": 0, "recovery": 0, "loop": 0, "context": 0, "policy": 0, "model_insufficient": 0}
        for row in db.all("SELECT category,message FROM failures WHERE task_id=?", (task_id,)):
            message = f"{row['category']} {row['message']}".lower()
            if "verifica" in message:
                categories["verification"] += 1
            elif "policy" in message or "bloque" in message:
                categories["policy"] += 1
            elif "tool" in message or "arquivo" in message:
                categories["tool"] += 1
            else:
                categories["recovery"] += 1
        return categories

    async def run_async(self, *, limit: int | None = None) -> ForgeE2EResult:
        tasks = self._tasks()[:limit] if limit else self._tasks()
        contracts = json.loads((self.private_root / "contracts.json").read_text(encoding="utf-8"))
        evaluator = _load_private_evaluator(self.private_root / "evaluator.py")
        run_id = str(uuid4())
        artifact_dir = self.settings.artifacts_dir / "research" / "forge" / "e2e_generative" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        traces: list[dict] = []
        for mission in tasks:
            task_id = str(mission["id"])
            workspace = f"forge_{run_id[:8]}_{task_id}"
            orchestrator = self._orchestrator(list(mission["allowed_tools"]))
            workspace_path = orchestrator.tools.workspace_for(workspace)
            evaluator.prepare(workspace_path, task_id, contracts[task_id])
            created = await orchestrator.create_task(
                TaskCreate(
                    title=str(mission["title"]),
                    objective=(
                        f"{mission['objective']}\n"
                        "Para esta missão benchmark, use python.execute para criar artefatos no workspace; "
                        "não use file.write, que exige aprovação humana."
                    ),
                    workspace=workspace,
                    autonomy_mode=4,
                )
            )
            started = monotonic()
            await orchestrator.run(created["id"])
            active = orchestrator.active.get(created["id"])
            if active:
                await active
            task = orchestrator.get_task(created["id"]) or {}
            evaluation = evaluator.evaluate(workspace_path, task_id, contracts[task_id])
            model_call = self.db.one(
                "SELECT id,model,latency_ms,prompt_tokens,output_tokens,finish_reason FROM model_calls WHERE task_id=? AND purpose='planning' ORDER BY created_at DESC LIMIT 1",
                (created["id"],),
            )
            approvals = self.db.one("SELECT COUNT(*) AS count FROM approvals WHERE task_id=?", (created["id"],)) or {"count": 0}
            taxonomy = self._failure_taxonomy(self.db, str(created["id"]))
            if task.get("status") == "waiting_approval":
                taxonomy["policy"] += 1
            traces.append(
                {
                    "mission_id": task_id,
                    "private_evaluator_passed": bool(evaluation.get("passed")),
                    "private_evidence": evaluation.get("evidence", []),
                    "requested_model_alias": self.model_name,
                    "configured_model": self.configured_model,
                    "effective_model": model_call.get("model") if model_call else None,
                    "model_attribution_verified": bool(model_call and model_call.get("model") == self.configured_model),
                    "planner_source": orchestrator.plan_sources.get(str(created["id"]), "unavailable"),
                    "internal_task_status": task.get("status"),
                    "steps": int(task.get("step_count") or 0),
                    "replans": int(task.get("replan_count") or 0),
                    "tool_calls": int(task.get("tool_call_count") or 0),
                    "approval_requests": int(approvals["count"]),
                    "duration_ms": int((monotonic() - started) * 1000),
                    "failure_taxonomy": taxonomy,
                }
            )
        passed = sum(bool(trace["private_evaluator_passed"]) for trace in traces)
        invalidation_reasons = []
        if not all(trace["model_attribution_verified"] for trace in traces):
            invalidation_reasons.append("model_attribution_unverified")
        if not all(trace["planner_source"] == "model_structured" for trace in traces):
            invalidation_reasons.append("planner_not_structured_model_output")
        measurement_valid = not invalidation_reasons
        payload = {
            "benchmark": "forge_e2e_v1",
            "mode": "generative_real_planner",
            "requested_model_alias": self.model_name,
            "configured_model": self.configured_model,
            "seed": self.seed,
            "hardware": platform.platform(),
            "atc": round(passed / len(traces), 6) if traces else 0.0,
            "passed": passed,
            "total": len(traces),
            "measurement_valid": measurement_valid,
            "invalidation_reasons": invalidation_reasons,
            "forge_4_passed": measurement_valid and passed > 0,
            "forge_5_candidate": measurement_valid and any(trace["replans"] > 0 and trace["private_evaluator_passed"] for trace in traces),
            "traces": traces,
        }
        (artifact_dir / "e2e_generative.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ForgeE2EResult(run_id, len(traces), passed, float(payload["atc"]), artifact_dir)

    def run(self, *, limit: int | None = None) -> ForgeE2EResult:
        return asyncio.run(self.run_async(limit=limit))
