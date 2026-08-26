from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.configuration import Settings
from ultron.db import Database
from ultron.genesis.public_runner import (
    GENESIS_PUBLIC_TASK_IDS,
    GenesisPublicRunner,
    GenesisTaskResult,
)
from ultron.genesis.schemas import (
    GENESIS_MAX_OPERATORS,
    GENESIS_MAX_PROGRAMS,
    GENESIS_PROTOCOL_VERSION,
    CognitiveProgram,
    GenesisSummary,
)
from ultron.genesis.synthesizer import CognitiveProgramSynthesizer
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.models.gateway import ModelGateway


class GenesisController:
    """Coordena um único experimento Genesis sobre a Cognitive VM."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        *,
        runner: GenesisPublicRunner | Any | None = None,
        synthesizer: CognitiveProgramSynthesizer | Any | None = None,
        gateway: ModelGateway | Any | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.gateway = gateway or ModelGateway(settings)
        self.runner = runner or GenesisPublicRunner(settings)
        config = self.settings.raw.get("genesis", {})
        self.synthesizer = synthesizer or CognitiveProgramSynthesizer(
            self.gateway,
            model_name=str(config.get("model", "local-fallback")),
            seed=int(config.get("seed", 42)),
            max_tokens=int(config.get("max_tokens", 256)),
        )

    @property
    def config(self) -> dict[str, Any]:
        return self.settings.raw.get("genesis", {})

    @staticmethod
    def _fingerprint(task: Any) -> str:
        payload = task.model_dump(mode="json") if hasattr(task, "model_dump") else dict(task)
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _experiment_id(self, run_id: str) -> str:
        return f"genesis-experiment-{run_id}"

    def _write_experiment(
        self,
        *,
        experiment_id: str,
        status: str,
        report: dict[str, Any],
        baseline_score: float | None = None,
        candidate_score: float | None = None,
        candidate_version: str = "unselected",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            "INSERT OR REPLACE INTO experiments (id,hypothesis,baseline_version,candidate_version,benchmark,baseline_score,candidate_score,regression_score,status,report,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT created_at FROM experiments WHERE id=?),?),?)",
            (
                experiment_id,
                "Self-generated Cognitive Program executed by Cognitive VM",
                "genesis-v0.2-baseline",
                candidate_version,
                "genesis_public",
                baseline_score,
                candidate_score,
                None,
                status,
                self.db.json(report),
                experiment_id,
                now,
                now,
            ),
        )

    @staticmethod
    def _task_map(tasks: list[Any]) -> dict[str, Any]:
        return {str(task.id): task for task in tasks}

    def _protocol_tasks(self, tasks: list[Any]) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        task_map = self._task_map(tasks)
        diagnosis_ids = tuple(str(item) for item in self.config.get("diagnosis_task_ids", ["reasoning_01", "reasoning_02"]))
        holdout_ids = tuple(str(item) for item in self.config.get("holdout_task_ids", ["reasoning_06", "reasoning_07"]))
        if len(diagnosis_ids) != 2 or len(holdout_ids) != 2 or set(diagnosis_ids) & set(holdout_ids):
            raise ValueError("genesis_task_split_invalid")
        if set(diagnosis_ids + holdout_ids) != set(GENESIS_PUBLIC_TASK_IDS):
            raise ValueError("genesis_task_split_not_public_protocol")
        selected = [task_map.get(task_id) for task_id in diagnosis_ids + holdout_ids]
        if any(task is None for task in selected):
            raise ValueError("genesis_public_task_missing")
        if any(task.hidden or task.category != "reasoning" or task.allowed_tools for task in selected):
            raise ValueError("genesis_task_contract_invalid")
        return tuple(task_map[task_id] for task_id in diagnosis_ids), tuple(task_map[task_id] for task_id in holdout_ids)

    @staticmethod
    def _record(result: GenesisTaskResult, program: CognitiveProgram | None) -> dict[str, Any]:
        return {
            "task_id": result.task.id,
            "condition": result.condition,
            "program_id": program.id if program else None,
            "model": result.manifest.model,
            "seed": result.manifest.seed,
            "config_hash": result.manifest.config_hash,
            "task_fingerprint": GenesisController._fingerprint(result.task),
            "score": result.evaluation.score,
            "success": result.evaluation.success,
            "output_valid": bool(result.execution.response.strip()) and result.execution.failure_category is None,
            "vm_valid": result.vm_execution is None or result.vm_execution.valid,
            "vm_steps": result.vm_execution.steps if result.vm_execution else 0,
            "failure_category": result.execution.failure_category,
            "evidence_count": len(result.evaluation.evidence),
            "evidence": list(result.evaluation.evidence),
            "duration_ms": result.execution.duration_ms,
        }

    @staticmethod
    def _diagnosis_observation(result: GenesisTaskResult) -> dict[str, Any]:
        return {
            "task_id": result.task.id,
            "objective": result.task.objective,
            "response": result.execution.response[:1000],
            "success": result.evaluation.success,
            "score": result.evaluation.score,
            "errors": ["diagnostic failure observed"] if not result.evaluation.success else [],
        }

    @staticmethod
    def _pair_reason(left: dict[str, Any], right: dict[str, Any]) -> str | None:
        for field in ("model", "seed", "config_hash", "task_fingerprint"):
            if left[field] != right[field]:
                return f"{field}_mismatch:{left['task_id']}"
        if left["task_id"] != right["task_id"]:
            return "task_id_mismatch"
        for record in (left, right):
            if not record["output_valid"] or not record["vm_valid"]:
                return f"invalid_execution:{record['task_id']}"
            if record["evidence_count"] < 1:
                return f"insufficient_evidence:{record['task_id']}"
            if not 0.0 <= float(record["score"]) <= 1.0:
                return f"invalid_score:{record['task_id']}"
        if right["score"] < left["score"]:
            return f"regression:{left['task_id']}"
        return None

    async def _run_tasks(
        self,
        tasks: tuple[Any, ...],
        *,
        condition: str,
        run_id: str,
        model_name: str,
        seed: int,
        max_tokens: int,
        program: CognitiveProgram | None = None,
    ) -> list[GenesisTaskResult]:
        results: list[GenesisTaskResult] = []
        for task in tasks:
            result = await self.runner.run_one(
                task=task,
                condition=condition,
                run_id=run_id,
                model_name=model_name,
                seed=seed,
                max_tokens=max_tokens,
                program=program,
                call_budget=4 if condition == "program" else 1,
            )
            self.runner.persist_result(result)
            results.append(result)
        return results

    def _persist_experience(self, experiment_id: str, program: CognitiveProgram, ncpg: float, status: str) -> str:
        experience_id = f"genesis-experience-{experiment_id}"
        self.db.execute(
            "INSERT OR REPLACE INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,verification_state,verified_writeback_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                experience_id,
                None,
                f"Genesis VM Cognitive Program {program.id}",
                self.db.json([{"protocol": GENESIS_PROTOCOL_VERSION, "vm": True, "operators": program.operators}]),
                f"NCPG holdout={ncpg:.6f}; status={status}",
                int(status == "verified"),
                self.db.json([] if status == "verified" else ["ncpg_not_verified"]),
                self.db.json(["Program retained as VM operator sequence; rationale is audit metadata only."]),
                max(0.0, min(1.0, 0.5 + ncpg / 2)),
                "pending" if status == "pending" else "rejected",
                None,
                datetime.now(UTC).isoformat(),
            ),
        )
        return experience_id

    async def run(self, *, run_id: str | None = None) -> GenesisSummary:
        run_id = run_id or f"genesis-{uuid4()}"
        experiment_id = self._experiment_id(run_id)
        if not self.config.get("enabled", False) or not all(self.config.get("feature_flags", {}).get(flag, False) for flag in ("synthesis", "holdout")):
            return GenesisSummary(run_id, "rejected", "genesis_disabled", experiment_id)
        max_programs = int(self.config.get("max_programs", GENESIS_MAX_PROGRAMS))
        max_operators = int(self.config.get("max_operators", GENESIS_MAX_OPERATORS))
        max_runtime = int(self.config.get("max_runtime_seconds", 540))
        max_tokens = int(self.config.get("max_tokens", 256))
        model_name = str(self.config.get("model", "local-fallback"))
        seed = int(self.config.get("seed", 42))
        if not 1 <= max_programs <= GENESIS_MAX_PROGRAMS or not 1 <= max_operators <= GENESIS_MAX_OPERATORS:
            return GenesisSummary(run_id, "rejected", "invalid_program_budget", experiment_id)
        if not 1 <= max_runtime <= 600 or max_tokens < 1:
            return GenesisSummary(run_id, "rejected", "invalid_runtime_budget", experiment_id)
        writeback_enabled = bool(self.config.get("feature_flags", {}).get("writeback", False))
        self._write_experiment(experiment_id=experiment_id, status="running", report={"protocol_version": GENESIS_PROTOCOL_VERSION, "run_id": run_id})
        try:
            diagnosis_tasks, holdout_tasks = self._protocol_tasks(self.runner.load_tasks())
            async with asyncio.timeout(max_runtime):
                baseline_diagnosis = await self._run_tasks(
                    diagnosis_tasks,
                    condition="direct",
                    run_id=run_id,
                    model_name=model_name,
                    seed=seed,
                    max_tokens=max_tokens,
                )
                diagnosis = [self._diagnosis_observation(result) for result in baseline_diagnosis]
                batch = await self.synthesizer.generate(diagnosis, max_programs=max_programs, max_operators=max_operators)
                programs = list(batch.programs)
                if not 1 <= len(programs) <= max_programs:
                    raise ValueError("generated_program_count_invalid")
                program_diagnosis: dict[str, list[dict[str, Any]]] = {}
                for program in programs:
                    results = await self._run_tasks(
                        diagnosis_tasks,
                        condition="program",
                        run_id=run_id,
                        model_name=model_name,
                        seed=seed,
                        max_tokens=max_tokens,
                        program=program,
                    )
                    program_diagnosis[program.id] = [self._record(result, program) for result in results]
                selected = max(
                    enumerate(programs),
                    key=lambda pair: (sum(item["score"] for item in program_diagnosis[pair[1].id]) / len(diagnosis_tasks), -pair[0]),
                )[1]
                baseline_holdout = await self._run_tasks(
                    holdout_tasks,
                    condition="direct",
                    run_id=run_id,
                    model_name=model_name,
                    seed=seed,
                    max_tokens=max_tokens,
                )
                selected_holdout = await self._run_tasks(
                    holdout_tasks,
                    condition="program",
                    run_id=run_id,
                    model_name=model_name,
                    seed=seed,
                    max_tokens=max_tokens,
                    program=selected,
                )
            baseline_records = [self._record(result, None) for result in baseline_holdout]
            selected_records = [self._record(result, selected) for result in selected_holdout]
            reason = None
            for left, right in zip(baseline_records, selected_records, strict=True):
                reason = self._pair_reason(left, right)
                if reason:
                    break
            if reason is None and {item["task_id"] for item in baseline_records} != set(str(task.id) for task in holdout_tasks):
                reason = "holdout_task_set_mismatch"
            baseline_score = round(sum(item["score"] for item in baseline_records) / len(baseline_records), 6)
            selected_score = round(sum(item["score"] for item in selected_records) / len(selected_records), 6)
            ncpg = round(selected_score - baseline_score, 6)
            if reason is None and ncpg <= 0:
                reason = "no_positive_ncpg"
            all_executions = len(baseline_diagnosis) + sum(len(items) for items in program_diagnosis.values()) + len(baseline_records) + len(selected_records)
            report = {
                "protocol_version": GENESIS_PROTOCOL_VERSION,
                "run_id": run_id,
                "diagnosis_task_ids": [task.id for task in diagnosis_tasks],
                "holdout_task_ids": [task.id for task in holdout_tasks],
                "programs": [program.model_dump(mode="json") for program in programs],
                "selected_program_id": selected.id,
                "diagnosis_observations_sent_to_synthesizer": diagnosis,
                "holdout_sent_to_synthesizer": False,
                "rationale_used_for_execution": False,
                "human_selected_program": False,
                "baseline_holdout": baseline_records,
                "selected_holdout": selected_records,
                "program_diagnosis": program_diagnosis,
                "baseline_holdout_score": baseline_score,
                "selected_holdout_score": selected_score,
                "ncpg": ncpg,
                "executions": all_executions,
                "model": model_name,
                "seed": seed,
                "max_tokens": max_tokens,
                "allowlist": [],
                "vm_max_steps": max_operators,
                "writeback_enabled": writeback_enabled,
                "validation_reason": reason,
            }
            if reason is not None or not writeback_enabled:
                final_reason = reason or "writeback_disabled"
                self._write_experiment(
                    experiment_id=experiment_id,
                    status="rejected",
                    report={**report, "reason": final_reason},
                    baseline_score=baseline_score,
                    candidate_score=selected_score,
                    candidate_version=selected.id,
                )
                return GenesisSummary(run_id, "rejected", final_reason, experiment_id, tuple(task.id for task in diagnosis_tasks), tuple(task.id for task in holdout_tasks), tuple(program.id for program in programs), selected.id, baseline_score, selected_score, ncpg, all_executions)
            experience_id = self._persist_experience(experiment_id, selected, ncpg, "pending")
            evidence_refs = [f"genesis:{experiment_id}:baseline_holdout", f"genesis:{experiment_id}:selected_holdout", f"genesis:{experiment_id}:ncpg"]
            outcome = OutcomeAuthority().decide(task_verifier={"accepted": True, "evidence": evidence_refs, "confidence": 1.0})
            decision = VerifiedWritebackGate(self.db).evaluate(task_id=None, target_type="experience", target_id=experience_id, outcome_result=outcome)
            if not decision.allowed:
                self.db.execute("UPDATE experiences SET verification_state='rejected' WHERE id=?", (experience_id,))
                report["writeback"] = asdict(decision)
                self._write_experiment(experiment_id=experiment_id, status="rejected", report={**report, "reason": "writeback_denied"}, baseline_score=baseline_score, candidate_score=selected_score, candidate_version=selected.id)
                return GenesisSummary(run_id, "rejected", "writeback_denied", experiment_id, tuple(task.id for task in diagnosis_tasks), tuple(task.id for task in holdout_tasks), tuple(program.id for program in programs), selected.id, baseline_score, selected_score, ncpg, all_executions)
            self.db.execute("UPDATE experiences SET verification_state='verified',verified_writeback_id=? WHERE id=?", (decision.audit_id, experience_id))
            ExperienceSignatureBuilder.persist(
                self.db,
                ExperienceSignature(
                    category="reasoning",
                    family="unknown",
                    domain="reasoning",
                    abstraction_level=0.5,
                    verified=True,
                    historical_utility=ncpg,
                    sample_count=len(holdout_tasks),
                    source="genesis_vm_verified_holdout",
                ),
                experience_id,
            )
            report["writeback"] = {"audit_id": decision.audit_id, "experience_id": experience_id, "retained": True, "reusable": False}
            self._write_experiment(experiment_id=experiment_id, status="promoted", report=report, baseline_score=baseline_score, candidate_score=selected_score, candidate_version=selected.id)
            return GenesisSummary(run_id, "promoted", "positive_ncpg_verified", experiment_id, tuple(task.id for task in diagnosis_tasks), tuple(task.id for task in holdout_tasks), tuple(program.id for program in programs), selected.id, baseline_score, selected_score, ncpg, all_executions, decision.audit_id, True)
        except TimeoutError:
            self._write_experiment(experiment_id=experiment_id, status="rejected", report={"protocol_version": GENESIS_PROTOCOL_VERSION, "run_id": run_id, "reason": "total_timeout", "max_runtime_seconds": max_runtime})
            return GenesisSummary(run_id, "rejected", "total_timeout", experiment_id)
        except Exception as exc:
            self._write_experiment(experiment_id=experiment_id, status="rejected", report={"protocol_version": GENESIS_PROTOCOL_VERSION, "run_id": run_id, "reason": f"execution_error:{type(exc).__name__}", "error": str(exc)[:500]})
            return GenesisSummary(run_id, "rejected", f"execution_error:{type(exc).__name__}", experiment_id)
