"""Runner comparativo Horizon: mesma missão, contrato, seed e evaluator sob três arquiteturas de controle."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import platform
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import uuid4

import yaml

from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import TaskCreate
from ultron.tools.registry import ToolRegistry

MODES = ("full_plan", "short_horizon", "next_action")


@dataclass(frozen=True, slots=True)
class HorizonRunResult:
    run_id: str
    artifact_dir: Path
    total: int
    measurement_valid: bool


def _load_private_evaluator(path: Path):
    spec = importlib.util.spec_from_file_location("horizon_private_evaluator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Avaliador privado Horizon indisponível")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


class HorizonControlRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        public_root: Path | None = None,
        private_root: Path | None = None,
        model_name: str = "ollama_research",
        seed: int = 53,
    ):
        self.settings = Settings(raw=deepcopy(settings.raw), root_dir=settings.root_dir)
        self.public_root = public_root or self.settings.root_dir / "benchmarks" / "forge_e2e_v1"
        configured = private_root or self.settings.private_benchmark_root
        if configured is None:
            raise FileNotFoundError("Horizon exige raiz privada externa configurada.")
        self.private_root = configured / "forge_e2e_v1" if not (configured / "contracts.json").exists() else configured
        if model_name not in self.settings.raw["models"]["registry"]:
            raise ValueError(f"Modelo Horizon não registrado: {model_name}")
        self.model_name, self.seed = model_name, seed
        self.settings.raw["models"]["primary"] = model_name
        self.settings.raw["models"]["timeout_seconds"] = max(300, int(self.settings.raw["models"].get("timeout_seconds", 120)))
        self.configured_model = str(self.settings.raw["models"]["registry"][model_name].get("model", model_name))

    def _tasks(self) -> list[dict]:
        tasks = yaml.safe_load((self.public_root / "tasks.yaml").read_text(encoding="utf-8")) or []
        if not isinstance(tasks, list) or len(tasks) != 10:
            raise ValueError("Horizon Control v1 exige as dez missões Forge públicas")
        return tasks

    def _orchestrator(self, db: Database, mode: str, allowed_tools: list[str]) -> Orchestrator:
        mode_settings = Settings(raw=deepcopy(self.settings.raw), root_dir=self.settings.root_dir)
        mode_settings.raw["cognition"]["controller_mode"] = mode
        models = ModelGateway(mode_settings)
        tools = ToolRegistry(mode_settings)
        unavailable = set(allowed_tools).difference(tools.manifests)
        if unavailable:
            raise ValueError(f"Ferramentas Horizon indisponíveis: {sorted(unavailable)}")
        tools.manifests = {name: manifest for name, manifest in tools.manifests.items() if name in allowed_tools}
        tools.handlers = {name: handler for name, handler in tools.handlers.items() if name in allowed_tools}
        orchestrator = Orchestrator(
            mode_settings,
            db,
            EventBus(db),
            MemoryService(db, mode_settings),
            models,
            PolicyEngine(mode_settings),
            tools,
            planning_seed=self.seed,
        )
        # O benchmark mede controle, não aprendizagem por experiência prévia.
        orchestrator.context_builder.injection_limit = 0
        return orchestrator

    async def run_async(self, *, limit: int = 3, modes: tuple[str, ...] = MODES) -> HorizonRunResult:
        if not set(modes).issubset(MODES):
            raise ValueError("Modo Horizon inválido")
        tasks = self._tasks()[:limit]
        contracts_path = self.private_root / "contracts.json"
        evaluator_path = self.private_root / "evaluator.py"
        contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
        evaluator = _load_private_evaluator(evaluator_path)
        run_id = str(uuid4())
        artifact_dir = self.settings.artifacts_dir / "research" / "horizon" / "comparisons" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        db = Database(artifact_dir / "horizon_runtime.db")
        db.initialize()
        authority = OutcomeAuthority()
        traces: list[dict] = []

        for mission in tasks:
            for mode in modes:
                task_id = str(mission["id"])
                workspace = f"horizon_{run_id[:8]}_{mode}_{task_id}"
                orchestrator = self._orchestrator(db, mode, [str(name) for name in mission["allowed_tools"]])
                workspace_path = orchestrator.tools.workspace_for(workspace)
                evaluator.prepare(workspace_path, task_id, contracts[task_id])
                created = await orchestrator.create_task(
                    TaskCreate(
                        title=str(mission["title"]),
                        objective=str(mission["objective"]),
                        workspace=workspace,
                        autonomy_mode=4,
                        allowed_tools=[str(name) for name in mission["allowed_tools"]],
                        action_budget=(int(mission["action_budget"][0]), int(mission["action_budget"][1])),
                        requires_external_outcome=True,
                    )
                )
                started = monotonic()
                await orchestrator.run(created["id"])
                active = orchestrator.active.get(created["id"])
                if active:
                    await active
                task = orchestrator.get_task(created["id"]) or {}
                external = evaluator.evaluate(workspace_path, task_id, contracts[task_id])
                if task.get("status") == "waiting_outcome":
                    outcome = await orchestrator.resolve_external_outcome(created["id"], external)
                    active = orchestrator.active.get(created["id"])
                    if active:
                        await active
                    task = orchestrator.get_task(created["id"]) or {}
                else:
                    outcome = authority.decide(private_evaluation=external)
                model_calls = db.all(
                    "SELECT model,seed,purpose,latency_ms,prompt_tokens,output_tokens FROM model_calls WHERE task_id=? ORDER BY created_at,rowid",
                    (created["id"],),
                )
                tool_rows = db.all("SELECT tool_name,status FROM tool_executions WHERE task_id=? ORDER BY created_at,rowid", (created["id"],))
                actions = db.all("SELECT status FROM cognitive_actions WHERE task_id=? ORDER BY created_at,rowid", (created["id"],))
                planner_source = orchestrator.plan_sources.get(created["id"], "model_structured" if actions else "fallback_control")
                if mode != "full_plan" and actions:
                    planner_source = "model_repaired" if any(call["purpose"].endswith("_repair") for call in model_calls) else "model_structured"
                mission_tools = [str(name) for name in mission["allowed_tools"]]
                mission_budget = [int(mission["action_budget"][0]), int(mission["action_budget"][1])]
                trace = {
                    "mission_id": task_id,
                    "controller_mode": mode,
                    "requested_model_alias": self.model_name,
                    "configured_model": self.configured_model,
                    "seed": self.seed,
                    "mission_allowed_tools": mission_tools,
                    "mission_action_budget": mission_budget,
                    "task_allowed_tools": task.get("allowed_tools"),
                    "task_action_budget": task.get("action_budget"),
                    "mission_contract_verified": task.get("allowed_tools") == mission_tools and task.get("action_budget") == mission_budget,
                    "effective_models": [call["model"] for call in model_calls],
                    "effective_seeds": [call["seed"] for call in model_calls],
                    "model_attribution_verified": bool(model_calls) and all(call["model"] == self.configured_model for call in model_calls),
                    "seed_attribution_verified": bool(model_calls) and all(call["seed"] == self.seed for call in model_calls),
                    "tool_contract_respected": all(row["tool_name"] in mission_tools for row in tool_rows),
                    "action_budget_cap_respected": int(task.get("tool_call_count") or 0) <= mission_budget[1],
                    "planner_source": planner_source,
                    "internal_completion": task.get("status") == "completed",
                    "external_success": outcome.success,
                    "model_cognitive_success": outcome.success and planner_source in {"model_structured", "model_repaired"},
                    "outcome_authority_level": outcome.authority_level,
                    "experience_written": False,
                    "experience_verified": False,
                    "sdv_numerator": sum(1 for call in model_calls if not call["purpose"].endswith("_repair")),
                    "sdv_denominator": max(1, len(model_calls)),
                    "tool_calls": int(task.get("tool_call_count") or 0),
                    "llm_calls": int(task.get("llm_call_count") or 0),
                    "invalid_structured_outputs": int(not actions and mode != "full_plan"),
                    "repair_attempts": sum(1 for call in model_calls if call["purpose"].endswith("_repair")),
                    "false_stops": len([row for row in db.all("SELECT event_type FROM execution_traces WHERE task_id=?", (created["id"],)) if row["event_type"] == "cognition.false_stop"]),
                    "stagnation_events": len([row for row in db.all("SELECT event_type FROM execution_traces WHERE task_id=?", (created["id"],)) if row["event_type"] == "cognition.stagnation"]),
                    "action_loops": len([row for row in db.all("SELECT event_type FROM execution_traces WHERE task_id=?", (created["id"],)) if row["event_type"] == "cognition.action_loop"]),
                    "duration_ms": int((monotonic() - started) * 1000),
                }
                traces.append(trace)

        invalidation_reasons: list[str] = []
        for trace in traces:
            if not trace["model_attribution_verified"]:
                invalidation_reasons.append("model_attribution_unverified")
            if not trace["seed_attribution_verified"]:
                invalidation_reasons.append("seed_attribution_unverified")
            if not trace["mission_contract_verified"]:
                invalidation_reasons.append("mission_contract_unverified")
            if not trace["tool_contract_respected"]:
                invalidation_reasons.append("allowed_tool_contract_violated")
            if not trace["action_budget_cap_respected"]:
                invalidation_reasons.append("action_budget_cap_exceeded")
        summaries = {mode: self._summarize([trace for trace in traces if trace["controller_mode"] == mode]) for mode in modes}
        full_atc = summaries.get("full_plan", {}).get("atc", 0.0)
        payload = {
            "benchmark": "horizon_control_v1",
            "commit": _git_commit(self.settings.root_dir),
            "hardware": platform.platform(),
            "model_alias": self.model_name,
            "effective_model": self.configured_model,
            "seed": self.seed,
            "modes": list(modes),
            "measurement_valid": not invalidation_reasons,
            "invalidation_reasons": sorted(set(invalidation_reasons)),
            "summaries": summaries,
            "closed_loop_lift": round(summaries.get("next_action", {}).get("atc", 0.0) - full_atc, 6),
            "short_horizon_lift": round(summaries.get("short_horizon", {}).get("atc", 0.0) - full_atc, 6),
            "traces": traces,
            "private_evaluator_hash": _hash_path(evaluator_path),
            "mission_contract_hash": _hash_path(self.public_root / "tasks.yaml"),
        }
        (artifact_dir / "horizon_control.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return HorizonRunResult(run_id, artifact_dir, len(traces), bool(payload["measurement_valid"]))

    @staticmethod
    def _summarize(traces: list[dict]) -> dict:
        total = len(traces)
        passes = sum(bool(trace["model_cognitive_success"]) for trace in traces)
        structured = [trace for trace in traces if trace["planner_source"] in {"model_structured", "model_repaired"}]
        return {
            "total": total,
            "passed": passes,
            "atc": round(passes / total, 6) if total else 0.0,
            "sdv": round(len(structured) / total, 6) if total else 0.0,
            "mean_tool_calls": round(sum(trace["tool_calls"] for trace in traces) / total, 3) if total else 0.0,
            "mean_llm_calls": round(sum(trace["llm_calls"] for trace in traces) / total, 3) if total else 0.0,
        }

    def run(self, *, limit: int = 3, modes: tuple[str, ...] = MODES) -> HorizonRunResult:
        return asyncio.run(self.run_async(limit=limit, modes=modes))
