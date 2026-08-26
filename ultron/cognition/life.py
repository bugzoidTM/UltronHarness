from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ultron.benchmarks.models import BenchmarkTask
from ultron.cognition.outcome_authority import OutcomeAuthority
from ultron.cognition.self_model import EmpiricalSelfModel
from ultron.cognition.task_signature import TaskSignatureClassifier
from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignature, ExperienceSignatureBuilder
from ultron.learning.experience_utility import ExperienceUtilityModel
from ultron.learning.negative_transfer import NegativeTransferFirewall
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.research.cycle import SkillService

if TYPE_CHECKING:
    from ultron.benchmarks.runner import UGIBLiteRunner

from ultron.schemas import (
    CognitiveTension,
    EpistemicState,
    LifeGoalCandidate,
    LifeRunSummary,
    PersistentIntention,
    TaskCreate,
)

TensionKind = Literal[
    "UNKNOWN_IMPORTANT",
    "PREDICTION_ERROR",
    "COMPETENCE_GAP",
    "CONTRADICTION",
    "UNFINISHED_COMMITMENT",
]

_FORBIDDEN_GOAL_MARKERS = (
    "aumentar permiss",
    "increase permission",
    "obter credencia",
    "obtain credential",
    "replicar",
    "replicate",
    "evadir policy",
    "evadir política",
    "burlar política",
    "expandir acesso",
    "expand access",
    "alterar evaluator",
    "alter evaluator",
    "private evaluator",
    "autoimplant",
    "self-deploy",
)

SDCG_PUBLIC_TASK_IDS = ("reasoning_06", "reasoning_07", "reasoning_08")
SDCG_PROTOCOL_VERSION = "life-sdcg-v0.2"
SDCG_MAX_EXECUTIONS = 6
SDCG_MAX_RUNTIME_SECONDS = 600


@dataclass(frozen=True, slots=True)
class StrategyHypothesis:
    id: str
    gap_domain: str
    gap_task_type: str
    statement: str
    intervention: str
    selection_source: str = "life_gap_policy"
    protocol_version: str = SDCG_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class LifeSDCGSummary:
    run_id: str
    status: str
    reason: str
    tension_id: str | None = None
    goal_id: str | None = None
    hypothesis_id: str | None = None
    experiment_id: str | None = None
    task_ids: tuple[str, ...] = ()
    baseline_score: float | None = None
    candidate_score: float | None = None
    gain: float | None = None
    executions: int = 0
    writeback_id: str | None = None
    reusable: bool = False

    @property
    def promoted(self) -> bool:
        return bool(self.writeback_id and self.status == "promoted")


_DEFAULT_WEIGHTS = {
    "expected_information_gain": 0.30,
    "expected_capability_gain": 0.30,
    "importance": 0.20,
    "tractability": 0.10,
    "expected_transfer": 0.10,
    "estimated_cost": 0.10,
    "estimated_risk": 0.20,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _tension_id(run_id: str, kind: str, description: str, evidence_refs: list[str]) -> str:
    material = "|".join([kind, description, *sorted(evidence_refs)])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"tension-{run_id}-{digest}"


class LifeAgencyController:
    """Integra agência LIFE ao runtime existente sem criar planner ou executor paralelo."""

    def __init__(self, settings: Settings, db: Database, events: EventBus, orchestrator: Any):
        self.settings = settings
        self.db = db
        self.events = events
        self.orchestrator = orchestrator
        self.self_model = EmpiricalSelfModel(db)
        self.active: dict[str, asyncio.Task[LifeRunSummary]] = {}

    @property
    def config(self) -> dict[str, Any]:
        return self.settings.raw.get("life", {})

    @property
    def flags(self) -> dict[str, bool]:
        return self.config.get("feature_flags", {})

    def _enabled(self, flag: str) -> bool:
        return bool(self.config.get("enabled", False) and self.flags.get(flag, False))

    def _sdcg_enabled(self) -> bool:
        return self._enabled("sdcg")

    @staticmethod
    def _sdcg_task_fingerprint(task: BenchmarkTask) -> str:
        contract = {
            "id": task.id,
            "category": task.category,
            "objective": task.objective,
            "allowed_tools": list(task.allowed_tools),
            "timeout_seconds": task.timeout_seconds,
            "max_steps": task.max_steps,
            "evaluator": task.evaluator,
            "expected_artifacts": list(task.expected_artifacts),
        }
        return hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _sdcg_result_record(manifest: Any, item: Any, task_fingerprint: str) -> dict[str, Any]:
        evidence_digest = hashlib.sha256(
            json.dumps(list(item.evaluation.evidence), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return {
            "task_id": str(item.task.id),
            "model": str(manifest.model),
            "seed": int(manifest.seed),
            "config_hash": str(manifest.config_hash),
            "mode": str(manifest.mode),
            "task_fingerprint": task_fingerprint,
            "score": float(item.evaluation.score),
            "success": bool(item.evaluation.success),
            "failure_category": item.execution.failure_category,
            "output_valid": bool(item.execution.failure_category is None and item.execution.response.strip()),
            "evidence_count": len(item.evaluation.evidence),
            "evidence_digest": evidence_digest,
            "duration_ms": int(item.execution.duration_ms),
        }

    @staticmethod
    def _sdcg_gap_metadata(tension: CognitiveTension) -> tuple[str, str] | None:
        for reference in tension.evidence_refs:
            prefix = "capability_estimate:"
            if reference.startswith(prefix):
                payload = reference.removeprefix(prefix)
                if ":" in payload:
                    domain, task_type = payload.split(":", 1)
                    if domain and task_type:
                        return domain, task_type
        return None

    def formulate_strategy_hypothesis(self, tension: CognitiveTension) -> StrategyHypothesis | None:
        """Deriva uma única hipótese segura do tipo de lacuna, sem entrada humana intermediária."""
        if tension.kind != "COMPETENCE_GAP":
            return None
        metadata = self._sdcg_gap_metadata(tension)
        if metadata is None:
            return None
        domain, task_type = metadata
        interventions = {
            "representation": (
                "Representação explícita pode reduzir erros neste tipo de tarefa.",
                "Antes de responder, represente explicitamente o estado inicial, a transformação ou restrição principal e o estado desejado; depois verifique a consistência e respeite o formato solicitado.",
            ),
            "decomposition": (
                "Decomposição explícita pode reduzir erros neste tipo de tarefa.",
                "Antes de responder, divida o objetivo em passos mínimos verificáveis, resolva cada passo e confira a resposta final contra o objetivo.",
            ),
            "verification": (
                "Uma verificação final explícita pode reduzir erros neste tipo de tarefa.",
                "Resolva o objetivo e, antes de responder, faça uma verificação final independente da consistência, das restrições e do formato solicitado.",
            ),
            "memory": (
                "Uma recuperação seletiva de procedimento pode reduzir erros neste tipo de tarefa.",
                "Antes de responder, identifique o procedimento relevante já disponível, aplique somente os passos compatíveis com o objetivo e verifique o resultado.",
            ),
            "reasoning_order": (
                "Ordenar premissas antes da conclusão pode reduzir erros neste tipo de tarefa.",
                "Antes de responder, liste as premissas e restrições relevantes, derive a conclusão passo a passo e verifique se nenhuma premissa foi alterada.",
            ),
        }
        statement, intervention = interventions.get(
            task_type,
            (
                "Uma representação explícita do problema seguida de verificação pode reduzir erros neste tipo de tarefa.",
                "Antes de responder, represente explicitamente os dados, restrições e estado desejado; derive a resposta e verifique a consistência e o formato solicitado.",
            ),
        )
        return StrategyHypothesis(
            id=f"strategy-{uuid4()}",
            gap_domain=domain,
            gap_task_type=task_type,
            statement=statement,
            intervention=intervention,
        )

    def _persist_sdcg_experiment(
        self,
        *,
        experiment_id: str,
        hypothesis: StrategyHypothesis,
        benchmark: str,
        status: str,
        report: dict[str, Any],
        baseline_score: float | None = None,
        candidate_score: float | None = None,
    ) -> None:
        timestamp = _now()
        self.db.execute(
            "INSERT INTO experiments (id,hypothesis,baseline_version,candidate_version,benchmark,baseline_score,candidate_score,regression_score,status,report,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                experiment_id,
                hypothesis.statement,
                "public_baseline_no_intervention",
                hypothesis.id,
                benchmark,
                baseline_score,
                candidate_score,
                None,
                status,
                self.db.json(report),
                timestamp,
                timestamp,
            ),
        )

    def _update_sdcg_experiment(
        self,
        experiment_id: str,
        *,
        status: str,
        report: dict[str, Any],
        baseline_score: float | None = None,
        candidate_score: float | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE experiments SET baseline_score=?,candidate_score=?,status=?,report=?,updated_at=? WHERE id=?",
            (baseline_score, candidate_score, status, self.db.json(report), _now(), experiment_id),
        )

    def _sdcg_public_tasks(self, runner: UGIBLiteRunner, domain: str) -> tuple[BenchmarkTask, ...]:
        tasks = {task.id: task for task in runner.load_tasks()}
        missing = [task_id for task_id in SDCG_PUBLIC_TASK_IDS if task_id not in tasks]
        if missing:
            raise ValueError(f"public_tasks_missing:{','.join(missing)}")
        selected = tuple(tasks[task_id] for task_id in SDCG_PUBLIC_TASK_IDS)
        if any(task.category != domain for task in selected):
            raise ValueError("public_task_domain_mismatch")
        if any(task.hidden for task in selected):
            raise ValueError("public_task_hidden")
        return selected

    @staticmethod
    def _sdcg_pair_validation(
        baseline_records: dict[str, dict[str, Any]],
        candidate_records: dict[str, dict[str, Any]],
        *,
        baseline_manifests: list[Any],
        candidate_manifests: list[Any],
        expected_task_ids: tuple[str, ...],
        expected_seed: int,
    ) -> str | None:
        manifests = [*baseline_manifests, *candidate_manifests]
        if not manifests or len(manifests) != SDCG_MAX_EXECUTIONS:
            return "execution_count_mismatch"
        if {str(manifest.model) for manifest in manifests} != {str(baseline_manifests[0].model)}:
            return "model_mismatch"
        if any(int(manifest.seed) != expected_seed for manifest in manifests):
            return "seed_mismatch"
        if len({str(manifest.config_hash) for manifest in manifests}) != 1:
            return "config_mismatch"
        if any(str(baseline.mode) != str(candidate.mode) for baseline, candidate in zip(baseline_manifests, candidate_manifests, strict=True)):
            return "mode_mismatch"
        if tuple(sorted(baseline_records)) != tuple(sorted(expected_task_ids)) or tuple(sorted(candidate_records)) != tuple(sorted(expected_task_ids)):
            return "task_set_mismatch"
        for task_id in expected_task_ids:
            baseline = baseline_records[task_id]
            candidate = candidate_records[task_id]
            if baseline["task_fingerprint"] != candidate["task_fingerprint"]:
                return f"budget_or_allowlist_mismatch:{task_id}"
            if not baseline["output_valid"] or not candidate["output_valid"]:
                return f"invalid_output:{task_id}"
            if baseline["failure_category"] or candidate["failure_category"]:
                return f"execution_failure:{task_id}"
            if baseline["evidence_count"] < 1 or candidate["evidence_count"] < 1:
                return f"insufficient_evidence:{task_id}"
            if not 0.0 <= baseline["score"] <= 1.0 or not 0.0 <= candidate["score"] <= 1.0:
                return f"invalid_score:{task_id}"
            if candidate["score"] < baseline["score"]:
                return f"candidate_regression:{task_id}"
        return None

    def _sdcg_experience_id(self, experiment_id: str) -> str:
        return f"experience-{experiment_id}"

    def _persist_sdcg_experience(
        self,
        *,
        experience_id: str,
        task_type: str,
        hypothesis: StrategyHypothesis,
        result: str,
        success: bool,
        quality: float,
        verification_state: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,verification_state,verified_writeback_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                experience_id,
                None,
                f"LIFE SDCG {hypothesis.gap_domain}/{task_type}",
                self.db.json([{"kind": "bounded_behavioral_intervention", "protocol": SDCG_PROTOCOL_VERSION}]),
                result,
                int(success),
                self.db.json([] if success else ["sdcg_gain_not_verified"]),
                self.db.json([hypothesis.intervention]),
                quality,
                verification_state,
                None,
                _now(),
            ),
        )

    def _persist_sdcg_pairs(
        self,
        *,
        experiment_id: str,
        experience_id: str,
        tasks: tuple[BenchmarkTask, ...],
        baseline_records: dict[str, dict[str, Any]],
        candidate_records: dict[str, dict[str, Any]],
        hypothesis: StrategyHypothesis,
        seed: int,
    ) -> None:
        for task in tasks:
            task_signature = TaskSignatureClassifier.classify(task.model_dump(mode="json"))
            signature_id = TaskSignatureClassifier.persist(self.db, task_signature, task_id=None)
            ExperienceUtilityModel.record_pair_outcome(
                self.db,
                task_signature_id=signature_id,
                experience_id=experience_id,
                fresh_score=baseline_records[task.id]["score"],
                experienced_score=candidate_records[task.id]["score"],
                run_id=experiment_id,
                task_id=task.id,
                task_family=task_signature.family,
                experience_family="unknown",
                source_domain=hypothesis.gap_domain,
                target_domain=hypothesis.gap_domain,
                seed=seed,
                model_name=baseline_records[task.id]["model"],
                prompt_version=SDCG_PROTOCOL_VERSION,
                dataset_split="calibration",
            )

    async def _sdcg_condition_runs(
        self,
        *,
        runner: UGIBLiteRunner,
        tasks: tuple[BenchmarkTask, ...],
        mode: str,
        model_name: str,
        seed: int,
        experiment_id: str,
        extra_context: dict[str, str] | None = None,
    ) -> list[tuple[Any, Any]]:
        runs: list[tuple[Any, Any]] = []
        for task in tasks:
            manifest, summary = await runner.run_async(
                mode=mode, model_name=model_name, seed=seed, task_id=task.id, extra_context=extra_context
            )
            if len(summary.results) != 1 or summary.results[0].task.id != task.id:
                raise ValueError(f"unexpected_task_result:{task.id}")
            report_dir = self.settings.artifacts_dir / "life_sdcg" / experiment_id / mode / task.id
            report_dir.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, report_dir)
            runs.append((manifest, summary))
        return runs

    async def run_sdcg(self, *, run_id: str | None = None) -> LifeSDCGSummary:
        """Executa uma única investigação pública de ganho de capacidade, estritamente bounded."""
        run_id = run_id or f"life-sdcg-{uuid4()}"
        if not self._sdcg_enabled():
            return LifeSDCGSummary(run_id, "rejected", "sdcg_disabled")
        tensions = [item for item in self.detect_tensions(run_id) if item.kind == "COMPETENCE_GAP"]
        if not tensions:
            return LifeSDCGSummary(run_id, "rejected", "no_competence_gap")
        tension = tensions[0]
        self._persist_tension(run_id, tension)
        candidates = self.generate_goal_candidates([tension])
        goal = self.select_goal(candidates)
        if goal is None:
            return LifeSDCGSummary(run_id, "rejected", "goal_selection_unavailable", tension_id=tension.id)
        self._persist_candidate(run_id, goal, selected=True)
        hypothesis = self.formulate_strategy_hypothesis(tension)
        if hypothesis is None:
            return LifeSDCGSummary(run_id, "rejected", "gap_type_not_supported", tension_id=tension.id, goal_id=goal.id)
        experiment_id = f"experiment-{run_id}"
        benchmark = "ugib_lite_public"
        model_name = str(self.config.get("sdcg_model") or self.settings.raw.get("models", {}).get("research_primary", "local-fallback"))
        seed = int(self.config.get("sdcg_seed", 42))
        self._persist_sdcg_experiment(
            experiment_id=experiment_id,
            hypothesis=hypothesis,
            benchmark=benchmark,
            status="running",
            report={
                "protocol_version": SDCG_PROTOCOL_VERSION,
                "run_id": run_id,
                "tension_id": tension.id,
                "goal_id": goal.id,
                "hypothesis": asdict(hypothesis),
                "model_requested": model_name,
                "seed": seed,
                "max_executions": SDCG_MAX_EXECUTIONS,
                "candidate_context": {"strategy": hypothesis.intervention},
            },
        )
        configured_timeout = int(self.config.get("sdcg_max_runtime_seconds", 540))
        if configured_timeout < 1 or configured_timeout > SDCG_MAX_RUNTIME_SECONDS:
            reason = "invalid_runtime_budget"
            self._update_sdcg_experiment(experiment_id, status="rejected", report={"reason": reason})
            return LifeSDCGSummary(run_id, "rejected", reason, tension.id, goal.id, hypothesis.id, experiment_id)
        runner = getattr(self, "_sdcg_runner", None)
        if runner is None:
            from ultron.benchmarks.runner import UGIBLiteRunner

            runner = UGIBLiteRunner(self.settings)
        try:
            tasks = self._sdcg_public_tasks(runner, hypothesis.gap_domain)
            async with asyncio.timeout(configured_timeout):
                baseline_runs = await self._sdcg_condition_runs(
                    runner=runner,
                    tasks=tasks,
                    mode="baseline",
                    model_name=model_name,
                    seed=seed,
                    experiment_id=experiment_id,
                )
                candidate_runs = await self._sdcg_condition_runs(
                    runner=runner,
                    tasks=tasks,
                    mode="baseline",
                    model_name=model_name,
                    seed=seed,
                    experiment_id=experiment_id,
                    extra_context={"strategy": hypothesis.intervention},
                )
            baseline_manifests = [manifest for manifest, _ in baseline_runs]
            candidate_manifests = [manifest for manifest, _ in candidate_runs]
            baseline_records = {
                item.task.id: self._sdcg_result_record(manifest, item, self._sdcg_task_fingerprint(item.task))
                for manifest, summary in baseline_runs
                for item in summary.results
            }
            candidate_records = {
                item.task.id: self._sdcg_result_record(manifest, item, self._sdcg_task_fingerprint(item.task))
                for manifest, summary in candidate_runs
                for item in summary.results
            }
            reason = self._sdcg_pair_validation(
                baseline_records,
                candidate_records,
                baseline_manifests=baseline_manifests,
                candidate_manifests=candidate_manifests,
                expected_task_ids=tuple(task.id for task in tasks),
                expected_seed=seed,
            )
            baseline_score = round(sum(item["score"] for item in baseline_records.values()) / len(tasks), 6)
            candidate_score = round(sum(item["score"] for item in candidate_records.values()) / len(tasks), 6)
            gain = round(candidate_score - baseline_score, 6)
            report = {
                "protocol_version": SDCG_PROTOCOL_VERSION,
                "run_id": run_id,
                "tension": {"id": tension.id, "kind": tension.kind, "evidence_refs": tension.evidence_refs},
                "goal_id": goal.id,
                "hypothesis": {"id": hypothesis.id, "statement": hypothesis.statement, "intervention": hypothesis.intervention, "selection_source": hypothesis.selection_source},
                "model": baseline_manifests[0].model,
                "seed": seed,
                "task_ids": [task.id for task in tasks],
                "baseline": baseline_records,
                "candidate": candidate_records,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "gain": gain,
                "validation_reason": reason,
                "candidate_received_baseline_results": False,
            }
            experience_id = self._sdcg_experience_id(experiment_id)
            if reason is not None:
                self._update_sdcg_experiment(experiment_id, status="rejected", report=report, baseline_score=baseline_score, candidate_score=candidate_score)
                return LifeSDCGSummary(run_id, "rejected", reason, tension.id, goal.id, hypothesis.id, experiment_id, tuple(task.id for task in tasks), baseline_score, candidate_score, gain, SDCG_MAX_EXECUTIONS)
            self._persist_sdcg_experience(
                experience_id=experience_id,
                task_type=hypothesis.gap_task_type,
                hypothesis=hypothesis,
                result=f"Ganho pareado verificado no probe público: {gain:.6f}.",
                success=gain > 0,
                quality=candidate_score,
                verification_state="pending",
            )
            self._persist_sdcg_pairs(
                experiment_id=experiment_id,
                experience_id=experience_id,
                tasks=tasks,
                baseline_records=baseline_records,
                candidate_records=candidate_records,
                hypothesis=hypothesis,
                seed=seed,
            )
            if gain <= 0:
                outcome = OutcomeAuthority().decide(task_verifier={"accepted": False, "evidence": [f"sdcg:{experiment_id}:no_gain"]})
                decision = VerifiedWritebackGate(self.db).evaluate(task_id=None, target_type="experience", target_id=experience_id, outcome_result=outcome)
                self.db.execute("UPDATE experiences SET verification_state='rejected' WHERE id=?", (experience_id,))
                report["writeback"] = asdict(decision)
                self._update_sdcg_experiment(experiment_id, status="rejected", report=report, baseline_score=baseline_score, candidate_score=candidate_score)
                return LifeSDCGSummary(run_id, "rejected", "no_verified_gain", tension.id, goal.id, hypothesis.id, experiment_id, tuple(task.id for task in tasks), baseline_score, candidate_score, gain, SDCG_MAX_EXECUTIONS, None, False)
            evidence_refs = [f"sdcg:{experiment_id}:baseline", f"sdcg:{experiment_id}:candidate", f"sdcg:{experiment_id}:paired_gain"]
            outcome = OutcomeAuthority().decide(task_verifier={"accepted": True, "evidence": evidence_refs, "confidence": 1.0})
            experience_decision = VerifiedWritebackGate(self.db).evaluate(task_id=None, target_type="experience", target_id=experience_id, outcome_result=outcome)
            strategy_name = f"sdcg_{hypothesis.gap_domain}_{hypothesis.gap_task_type}_{experiment_id[-8:]}"
            skill_decision = VerifiedWritebackGate(self.db).evaluate(task_id=None, target_type="skill", target_id=strategy_name, outcome_result=outcome)
            if not experience_decision.allowed or not skill_decision.allowed:
                self.db.execute("UPDATE experiences SET verification_state='rejected' WHERE id=?", (experience_id,))
                report["writeback"] = {"experience": asdict(experience_decision), "skill": asdict(skill_decision)}
                self._update_sdcg_experiment(experiment_id, status="rejected", report=report, baseline_score=baseline_score, candidate_score=candidate_score)
                return LifeSDCGSummary(run_id, "rejected", "writeback_denied", tension.id, goal.id, hypothesis.id, experiment_id, tuple(task.id for task in tasks), baseline_score, candidate_score, gain, SDCG_MAX_EXECUTIONS, None, False)
            self.db.execute(
                "UPDATE experiences SET verification_state='verified',verified_writeback_id=? WHERE id=?",
                (experience_decision.audit_id, experience_id),
            )
            signature = ExperienceSignature(
                category=hypothesis.gap_domain,
                family="unknown",
                domain=hypothesis.gap_domain,
                abstraction_level=0.7,
                verified=True,
                historical_utility=gain,
                sample_count=len(tasks),
                source="life_sdcg_verified",
            )
            ExperienceSignatureBuilder.persist(self.db, signature, experience_id)
            skills = SkillService(self.db)
            for task_id in SDCG_PUBLIC_TASK_IDS:
                skills.observe(
                    strategy_name,
                    trigger=[f"COMPETENCE_GAP:{hypothesis.gap_domain}:{hypothesis.gap_task_type}"],
                    procedure=[hypothesis.intervention],
                    success=bool(candidate_records[task_id]["success"]),
                    verification_state="verified",
                    verified_writeback_id=skill_decision.audit_id,
                )
            utility = NegativeTransferFirewall.recalculate(self.db, "unknown", "unknown")
            reusable = skills.status(strategy_name) == "validated"
            report["writeback"] = {
                "experience_audit_id": experience_decision.audit_id,
                "skill_audit_id": skill_decision.audit_id,
                "skill_name": strategy_name,
                "family_utility_state": utility.state.value,
                "reusable": reusable,
            }
            self._update_sdcg_experiment(experiment_id, status="promoted", report=report, baseline_score=baseline_score, candidate_score=candidate_score)
            return LifeSDCGSummary(run_id, "promoted", "verified_gain", tension.id, goal.id, hypothesis.id, experiment_id, tuple(task.id for task in tasks), baseline_score, candidate_score, gain, SDCG_MAX_EXECUTIONS, experience_decision.audit_id, reusable)
        except TimeoutError:
            report = {"protocol_version": SDCG_PROTOCOL_VERSION, "reason": "total_timeout", "max_executions": SDCG_MAX_EXECUTIONS, "max_runtime_seconds": configured_timeout}
            self._update_sdcg_experiment(experiment_id, status="rejected", report=report)
            return LifeSDCGSummary(run_id, "rejected", "total_timeout", tension.id, goal.id, hypothesis.id, experiment_id)
        except Exception as exc:
            reason = f"execution_error:{type(exc).__name__}"
            self._update_sdcg_experiment(experiment_id, status="rejected", report={"protocol_version": SDCG_PROTOCOL_VERSION, "reason": reason, "error": str(exc)[:500]})
            return LifeSDCGSummary(run_id, "rejected", reason, tension.id, goal.id, hypothesis.id, experiment_id)

    @staticmethod
    def forbidden_goal(objective: str) -> bool:
        normalized = " ".join(objective.casefold().split())
        return any(marker in normalized for marker in _FORBIDDEN_GOAL_MARKERS)

    def _weights(self) -> dict[str, float]:
        configured = self.config.get("goal_value_weights", {})
        return {key: float(configured.get(key, value)) for key, value in _DEFAULT_WEIGHTS.items()}

    def _goal_value(self, candidate: LifeGoalCandidate) -> float:
        weights = self._weights()
        return (
            weights["expected_information_gain"] * candidate.expected_information_gain
            + weights["expected_capability_gain"] * candidate.expected_capability_gain
            + weights["importance"] * candidate.importance
            + weights["tractability"] * candidate.tractability
            + weights["expected_transfer"] * candidate.expected_transfer
            - weights["estimated_cost"] * candidate.estimated_cost
            - weights["estimated_risk"] * candidate.estimated_risk
        )

    def detect_tensions(
        self,
        run_id: str,
        state: EpistemicState | None = None,
        *,
        task_ids: set[str] | None = None,
    ) -> list[CognitiveTension]:
        """Detecta somente sinais persistidos ou claims tipados com referência de evidência."""
        if not self._enabled("tension_detection"):
            return []
        detected: list[CognitiveTension] = []
        created_at = _now()
        current = state or EpistemicState()
        for index, claim in enumerate(current.unknowns):
            if claim.evidence_refs:
                detected.append(
                    CognitiveTension(
                        id=_tension_id(run_id, "UNKNOWN_IMPORTANT", claim.content, list(claim.evidence_refs)),
                        kind="UNKNOWN_IMPORTANT",
                        description=claim.content,
                        importance=_bounded(1.0 - claim.confidence),
                        confidence=_bounded(1.0 - claim.confidence),
                        evidence_refs=list(claim.evidence_refs),
                        created_at=created_at,
                    )
                )
        scoped_task_ids = set(task_ids or set())
        scoped_task_ids.update(
            str(row["task_id"])
            for row in self.db.all(
                "SELECT task_id FROM life_intentions WHERE run_id=? AND task_id IS NOT NULL "
                "UNION SELECT task_id FROM life_cycles WHERE run_id=? AND task_id IS NOT NULL",
                (run_id, run_id),
            )
        )
        prediction_rows: list[dict[str, Any]] = []
        if scoped_task_ids:
            placeholders = ",".join("?" for _ in scoped_task_ids)
            prediction_rows = self.db.all(
                "SELECT prediction_id,classification,evidence_refs_json,observed_at,task_id FROM prediction_observations "
                f"WHERE classification IN ('reject','weaken') AND task_id IN ({placeholders}) "
                "ORDER BY observed_at DESC LIMIT 50",
                tuple(sorted(scoped_task_ids)),
            )
        for row in prediction_rows:
            evidence_refs = self.db.parse_json(row["evidence_refs_json"], [])
            evidence_refs = [str(item) for item in evidence_refs if str(item).strip()]
            if evidence_refs:
                detected.append(
                    CognitiveTension(
                        id=_tension_id(run_id, "PREDICTION_ERROR", str(row["prediction_id"]), evidence_refs),
                        kind="PREDICTION_ERROR",
                        description=f"Prediction outcome {row['classification']} requer investigação.",
                        importance=0.85 if row["classification"] == "reject" else 0.65,
                        confidence=0.9,
                        evidence_refs=evidence_refs,
                        created_at=created_at,
                    )
                )
        minimum = int(self.config.get("competence_min_sample", 2))
        threshold = float(self.config.get("competence_max_success_rate", 0.5))
        for row in self.db.all(
            "SELECT domain,task_type,success_rate,sample_size FROM capability_estimates "
            "WHERE sample_size >= ? AND success_rate <= ? ORDER BY success_rate ASC, domain, task_type",
            (minimum, threshold),
        ):
            detected.append(
                CognitiveTension(
                    id=_tension_id(run_id, "COMPETENCE_GAP", f"{row['domain']}:{row['task_type']}", [f"capability_estimate:{row['domain']}:{row['task_type']}"]),
                    kind="COMPETENCE_GAP",
                    description=(
                        f"Baixa taxa de sucesso observada em {row['domain']}/{row['task_type']} "
                        f"({row['success_rate']:.3f}, n={row['sample_size']})."
                    ),
                    importance=_bounded(1.0 - float(row["success_rate"])),
                    confidence=_bounded(min(1.0, float(row["sample_size"]) / max(1, minimum * 2))),
                    evidence_refs=[f"capability_estimate:{row['domain']}:{row['task_type']}"],
                    created_at=created_at,
                )
            )
        for index, contradiction in enumerate(current.contradictions):
            if contradiction.strip():
                detected.append(
                    CognitiveTension(
                        id=_tension_id(run_id, "CONTRADICTION", contradiction, [f"epistemic_state:contradiction:{index}"]),
                        kind="CONTRADICTION",
                        description=contradiction,
                        importance=0.9,
                        confidence=0.9,
                        evidence_refs=[f"epistemic_state:contradiction:{index}"],
                        created_at=created_at,
                    )
                )
        for row in self.db.all(
            "SELECT id,goal_id,objective,evidence_refs_json FROM life_intentions "
            "WHERE status='ACTIVE' AND run_id=? ORDER BY updated_at ASC",
            (run_id,),
        ):
            evidence_refs = self.db.parse_json(row["evidence_refs_json"], [])
            if evidence_refs:
                detected.append(
                    CognitiveTension(
                        id=_tension_id(run_id, "UNFINISHED_COMMITMENT", str(row["id"]), [f"life_intention:{row['id']}"]),
                        kind="UNFINISHED_COMMITMENT",
                        description=f"Compromisso ativo ainda não resolvido: {row['objective']}",
                        importance=0.95,
                        confidence=1.0,
                        evidence_refs=[*evidence_refs, f"life_intention:{row['id']}"],
                        created_at=created_at,
                    )
                )
        unique: dict[tuple[str, tuple[str, ...]], CognitiveTension] = {}
        for tension in detected:
            key = (tension.kind, tuple(sorted(tension.evidence_refs)))
            unique.setdefault(key, tension)
        return sorted(unique.values(), key=lambda item: (-item.importance, -item.confidence, item.id))

    def generate_goal_candidates(self, tensions: list[CognitiveTension]) -> list[LifeGoalCandidate]:
        if not self._enabled("goal_selection"):
            return []
        maximum = min(3, int(self.config.get("max_candidates", 3)))
        candidates: list[LifeGoalCandidate] = []
        templates = {
            "UNKNOWN_IMPORTANT": "Investigar e verificar o desconhecimento evidenciado: {description}",
            "PREDICTION_ERROR": "Investigar a causa do erro de previsão evidenciado: {description}",
            "COMPETENCE_GAP": "Executar uma investigação curta sobre a lacuna de competência evidenciada: {description}",
            "CONTRADICTION": "Resolver a contradição explicitamente evidenciada: {description}",
            "UNFINISHED_COMMITMENT": "Concluir ou desbloquear o compromisso persistente evidenciado: {description}",
        }
        profiles = {
            "UNKNOWN_IMPORTANT": (0.85, 0.55, 0.80, 0.75, 0.70, 0.20, 0.20),
            "PREDICTION_ERROR": (0.80, 0.65, 0.85, 0.70, 0.75, 0.25, 0.25),
            "COMPETENCE_GAP": (0.75, 0.85, 0.80, 0.60, 0.80, 0.35, 0.30),
            "CONTRADICTION": (0.90, 0.55, 0.90, 0.55, 0.70, 0.35, 0.35),
            "UNFINISHED_COMMITMENT": (0.65, 0.60, 0.95, 0.80, 0.65, 0.20, 0.25),
        }
        for tension in tensions:
            if len(candidates) >= maximum:
                break
            objective = templates[tension.kind].format(description=tension.description[:800])
            if self.forbidden_goal(objective):
                continue
            info, capability, importance, tractability, transfer, cost, risk = profiles[tension.kind]
            candidate = LifeGoalCandidate(
                id=f"goal-{uuid4()}",
                tension_id=tension.id,
                objective=objective,
                expected_information_gain=info,
                expected_capability_gain=capability,
                importance=_bounded(importance * tension.importance),
                tractability=tractability,
                expected_transfer=transfer,
                estimated_cost=cost,
                estimated_risk=risk,
            )
            candidates.append(candidate.model_copy(update={"goal_value": self._goal_value(candidate)}))
        return candidates

    def select_goal(self, candidates: list[LifeGoalCandidate]) -> LifeGoalCandidate | None:
        if not candidates or not self._enabled("goal_selection"):
            return None
        return sorted(candidates, key=lambda item: (-self._goal_value(item), item.estimated_cost, item.estimated_risk, item.id))[0]

    def _persist_tension(self, run_id: str, tension: CognitiveTension, task_id: str | None = None) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO life_tensions (id,run_id,task_id,kind,description,importance,confidence,evidence_refs_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tension.id, run_id, task_id, tension.kind, tension.description, tension.importance, tension.confidence, self.db.json(tension.evidence_refs), tension.created_at),
        )

    def _persist_candidate(self, run_id: str, candidate: LifeGoalCandidate, selected: bool = False) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO life_goal_candidates (id,run_id,tension_id,objective,expected_information_gain,expected_capability_gain,importance,tractability,expected_transfer,estimated_cost,estimated_risk,goal_value,selected,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate.id, run_id, candidate.tension_id, candidate.objective, candidate.expected_information_gain, candidate.expected_capability_gain, candidate.importance, candidate.tractability, candidate.expected_transfer, candidate.estimated_cost, candidate.estimated_risk, self._goal_value(candidate), int(selected), _now()),
        )

    def _persist_intention(self, run_id: str, intention_id: str, intention: PersistentIntention, task_id: str | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO life_intentions (id,run_id,goal_id,task_id,objective,status,started_at,cycle_budget,evidence_refs_json,new_evidence_refs_json,completed_at,blocked_reason,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (intention_id, run_id, intention.goal_id, task_id, intention.objective, intention.status, intention.started_at, intention.cycle_budget, self.db.json(intention.evidence_refs), self.db.json(intention.new_evidence_refs), intention.completed_at, intention.blocked_reason, _now()),
        )

    def _new_verified_evidence(self, task_id: str, baseline_refs: list[str]) -> list[str]:
        baseline = set(baseline_refs)
        rows = self.db.all(
            "SELECT prediction_id,evidence_refs_json,verification_passed,result_status,observed_at FROM prediction_observations "
            "WHERE task_id=? AND verification_passed=1 AND result_status NOT IN ('waiting_approval','waiting_outcome') ORDER BY observed_at",
            (task_id,),
        )
        evidence: list[str] = []
        for row in rows:
            refs = [str(item) for item in self.db.parse_json(row["evidence_refs_json"], []) if str(item).strip()]
            evidence.extend(refs or [f"prediction_observation:{row['prediction_id']}"])
        return list(dict.fromkeys(item for item in evidence if item not in baseline))

    def _active_intention(self, run_id: str) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM life_intentions WHERE run_id=? AND status='ACTIVE' ORDER BY updated_at LIMIT 1",
            (run_id,),
        )

    def _candidate_from_row(self, row: dict[str, Any]) -> LifeGoalCandidate:
        return LifeGoalCandidate(
            id=str(row["id"]),
            tension_id=str(row["tension_id"]),
            objective=str(row["objective"]),
            expected_information_gain=float(row["expected_information_gain"]),
            expected_capability_gain=float(row["expected_capability_gain"]),
            importance=float(row["importance"]),
            tractability=float(row["tractability"]),
            expected_transfer=float(row["expected_transfer"]),
            estimated_cost=float(row["estimated_cost"]),
            estimated_risk=float(row["estimated_risk"]),
            goal_value=float(row["goal_value"]),
        )

    def _intention_from_row(self, row: dict[str, Any]) -> PersistentIntention:
        return PersistentIntention(
            goal_id=str(row["goal_id"]),
            objective=str(row["objective"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            started_at=str(row["started_at"]),
            cycle_budget=int(row["cycle_budget"]),
            evidence_refs=[str(item) for item in self.db.parse_json(row["evidence_refs_json"], [])],
            new_evidence_refs=[str(item) for item in self.db.parse_json(row.get("new_evidence_refs_json"), [])],
            completed_at=row["completed_at"],
            blocked_reason=row["blocked_reason"],
        )

    def _intention_attempts(self, run_id: str, intention_id: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS count FROM life_cycles WHERE run_id=? AND intention_id=?",
            (run_id, intention_id),
        )
        return int(row["count"]) if row else 0

    def _update_intention(
        self,
        run_id: str,
        intention_id: str,
        status: str,
        *,
        reason: str | None = None,
        evidence_refs: list[str] | None = None,
        new_evidence_refs: list[str] | None = None,
    ) -> PersistentIntention:
        row = self.db.one("SELECT * FROM life_intentions WHERE id=? AND run_id=?", (intention_id, run_id))
        if not row:
            raise KeyError("Intenção LIFE não encontrada.")
        refs = evidence_refs or self.db.parse_json(row["evidence_refs_json"], [])
        fresh_refs = new_evidence_refs or self.db.parse_json(row.get("new_evidence_refs_json"), [])
        intention = PersistentIntention(
            goal_id=str(row["goal_id"]),
            objective=str(row["objective"]),
            status=status,  # type: ignore[arg-type]
            started_at=str(row["started_at"]),
            cycle_budget=int(row["cycle_budget"]),
            evidence_refs=refs,
            new_evidence_refs=fresh_refs,
            completed_at=_now() if status != "ACTIVE" else None,
            blocked_reason=reason,
        )
        self._persist_intention(run_id, intention_id, intention, row["task_id"])
        return intention

    def _metrics_from_records(self, run_id: str) -> dict[str, float | int]:
        tension_row = self.db.one("SELECT COUNT(*) AS count FROM life_tensions WHERE run_id=?", (run_id,))
        tensions = int(tension_row["count"]) if tension_row else 0
        goals_row = self.db.one("SELECT COUNT(DISTINCT goal_id) AS count FROM life_cycles WHERE run_id=?", (run_id,))
        goals_created = int(goals_row["count"]) if goals_row else 0
        completed_row = self.db.one(
            "SELECT COUNT(*) AS count FROM life_intentions WHERE run_id=? AND status='SATISFIED'",
            (run_id,),
        )
        completed = int(completed_row["count"]) if completed_row else 0
        intention_row = self.db.one("SELECT COUNT(*) AS count FROM life_intentions WHERE run_id=?", (run_id,))
        intentions = int(intention_row["count"]) if intention_row else 0
        resolved_row = self.db.one(
            "SELECT COUNT(*) AS count FROM life_intentions WHERE run_id=? AND status IN ('SATISFIED','ABANDONED','BLOCKED')",
            (run_id,),
        )
        resolved = int(resolved_row["count"]) if resolved_row else 0
        fresh_row = self.db.one(
            "SELECT COUNT(*) AS count FROM life_intentions WHERE run_id=? AND new_evidence_refs_json <> '[]'",
            (run_id,),
        )
        fresh = int(fresh_row["count"]) if fresh_row else 0
        prompt_row = self.db.one(
            "SELECT COUNT(*) AS count FROM events WHERE event_type='life.human_prompt.received' AND payload_json LIKE ?",
            (f'%"run_id":"{run_id}"%',),
        )
        prompt_count = int(prompt_row["count"]) if prompt_row else 0
        tool_row = self.db.one(
            "SELECT COUNT(*) AS count FROM tool_executions te JOIN life_cycles lc ON lc.task_id=te.task_id WHERE lc.run_id=?",
            (run_id,),
        )
        tool_calls = int(tool_row["count"]) if tool_row else 0
        return {
            "tensions_detected": tensions,
            "goals_created": goals_created,
            "goals_completed": completed,
            "agc": max(0, goals_created - 1),
            "ipr": resolved / intentions if intentions else 1.0,
            "eggr": fresh / intentions if intentions else 0.0,
            "human_prompts_after_initial_goal": prompt_count,
            "tool_calls": tool_calls,
        }

    async def _emit(self, event_type: str, run_id: str, payload: dict[str, Any], task_id: str | None = None) -> None:
        await self.events.emit(event_type, {"run_id": run_id, **payload}, task_id)

    def inspect(self, run_id: str) -> dict[str, Any] | None:
        tensions = self.db.all("SELECT * FROM life_tensions WHERE run_id=? ORDER BY created_at", (run_id,))
        candidates = self.db.all("SELECT * FROM life_goal_candidates WHERE run_id=? ORDER BY created_at", (run_id,))
        intentions = self.db.all("SELECT * FROM life_intentions WHERE run_id=? ORDER BY started_at", (run_id,))
        cycles = self.db.all("SELECT * FROM life_cycles WHERE run_id=? ORDER BY cycle_index", (run_id,))
        if not any((tensions, candidates, intentions, cycles)):
            return None
        for row in tensions:
            row["evidence_refs"] = self.db.parse_json(row.pop("evidence_refs_json"), [])
        for row in candidates:
            row["selected"] = bool(row["selected"])
        for row in intentions:
            row["evidence_refs"] = self.db.parse_json(row.pop("evidence_refs_json"), [])
            row["new_evidence_refs"] = self.db.parse_json(row.pop("new_evidence_refs_json", "[]"), [])
        for row in cycles:
            row["result"] = self.db.parse_json(row.pop("result_json"), {})
        metrics = self._metrics_from_records(run_id)
        return {
            "run_id": run_id,
            "superior_goal": cycles[0]["superior_goal"] if cycles else None,
            "status": cycles[-1]["status"] if cycles else "no_tension",
            "tensions": tensions,
            "candidates": candidates,
            "intentions": intentions,
            "cycles": cycles,
            "metrics": metrics,
        }

    async def _pursue(self, task: dict[str, Any]) -> dict[str, Any]:
        await self.orchestrator.run(str(task["id"]))
        runner = getattr(self.orchestrator, "active", {}).get(str(task["id"]))
        if runner is not None and hasattr(runner, "__await__"):
            await runner
        return self.orchestrator.get_task(str(task["id"])) or task

    async def run(
        self,
        superior_goal: str,
        *,
        run_id: str | None = None,
        workspace: str = "life",
        autonomy_mode: int = 2,
        allowed_tools: list[str] | None = None,
        initial_state: EpistemicState | None = None,
    ) -> LifeRunSummary:
        if not self.config.get("enabled", False):
            raise ValueError("LIFE está desabilitado na configuração.")
        run_id = run_id or f"life-{uuid4()}"
        if run_id in self.active:
            return await self.active[run_id]
        task = asyncio.create_task(
            self._run(
                superior_goal,
                run_id=run_id,
                workspace=workspace,
                autonomy_mode=autonomy_mode,
                allowed_tools=allowed_tools,
                initial_state=initial_state,
            ),
            name=f"life-run-{run_id}",
        )
        self.active[run_id] = task
        try:
            return await task
        finally:
            self.active.pop(run_id, None)

    async def _run(
        self,
        superior_goal: str,
        *,
        run_id: str,
        workspace: str,
        autonomy_mode: int,
        allowed_tools: list[str] | None,
        initial_state: EpistemicState | None,
    ) -> LifeRunSummary:
        max_goals = min(2, int(self.config.get("max_goals", 2)))
        max_actions = min(2, int(self.config.get("max_actions_per_goal", 2)))
        state = initial_state or EpistemicState()
        goals_created = 0

        status: Literal["completed", "blocked", "abandoned", "no_tension", "active"] = "no_tension"
        consumed_tensions: set[str] = set()
        max_cycles = max_goals * max(2, max_actions) + 1
        for cycle_index in range(max_cycles):
            active_row = self._active_intention(run_id)
            if goals_created >= max_goals and active_row is None:
                break
            if cycle_index > 0 and not self._enabled("autonomous_continuation"):
                break
            tensions = [
                tension for tension in self.detect_tensions(run_id, state) if tension.id not in consumed_tensions
            ]
            if not tensions:
                if cycle_index == 0:
                    await self._emit("life.cycle.completed", run_id, {"cycle_index": cycle_index, "status": "no_tension"})
                break
            if active_row is not None:
                active_intention = self._intention_from_row(active_row)
                if self._intention_attempts(run_id, str(active_row["id"])) >= active_intention.cycle_budget:
                    status = "active"
                    await self._emit(
                        "life.cycle.budget_exhausted",
                        run_id,
                        {"cycle_index": cycle_index, "intention_id": active_row["id"], "reason": "intention_attempt_budget_exhausted"},
                    )
                    break
            for tension in tensions:
                self._persist_tension(run_id, tension)
                await self._emit("life.tension.detected", run_id, {"tension": tension.model_dump(mode="json")})
            resumed = active_row is not None
            if resumed:
                intention_id = str(active_row["id"])
                candidate_row = self.db.one(
                    "SELECT * FROM life_goal_candidates WHERE run_id=? AND id=?",
                    (run_id, active_row["goal_id"]),
                )
                if candidate_row is None:
                    status = "blocked"
                    await self._emit("life.cycle.budget_exhausted", run_id, {"cycle_index": cycle_index, "reason": "active_intention_candidate_missing"})
                    break
                selected = self._candidate_from_row(candidate_row)
                intention = self._intention_from_row(active_row)
                consumed_tensions.add(selected.tension_id)
                await self._emit(
                    "life.intention.updated",
                    run_id,
                    {"intention_id": intention_id, "status": "ACTIVE", "attempt": self._intention_attempts(run_id, intention_id) + 1},
                    active_row["task_id"],
                )
            else:
                candidates = self.generate_goal_candidates(tensions)
                for candidate in candidates:
                    self._persist_candidate(run_id, candidate)
                await self._emit(
                    "life.goal_candidates.generated",
                    run_id,
                    {"count": len(candidates), "candidate_ids": [candidate.id for candidate in candidates]},
                )
                selected = self.select_goal(candidates)
                if selected is None:
                    status = "blocked"
                    await self._emit("life.cycle.budget_exhausted", run_id, {"cycle_index": cycle_index, "reason": "goal_selection_disabled"})
                    break
                self._persist_candidate(run_id, selected, selected=True)
                consumed_tensions.add(selected.tension_id)
                await self._emit("life.goal.selected", run_id, {"goal": selected.model_dump(mode="json"), "cycle_index": cycle_index})
                if not self._enabled("intention_persistence"):
                    status = "blocked"
                    await self._emit("life.cycle.budget_exhausted", run_id, {"cycle_index": cycle_index, "reason": "intention_persistence_disabled"})
                    break
                intention_id = f"intention-{uuid4()}"
                intention = PersistentIntention(
                    goal_id=selected.id,
                    objective=selected.objective,
                    status="ACTIVE",
                    started_at=_now(),
                    cycle_budget=max_actions,
                    evidence_refs=list(next(item for item in tensions if item.id == selected.tension_id).evidence_refs),
                )
            task_payload = TaskCreate(
                title=f"LIFE: {selected.objective[:170]}",
                objective=selected.objective,
                workspace=workspace,
                autonomy_mode=autonomy_mode,
                allowed_tools=allowed_tools,
                action_budget=(0, max_actions),
                requires_external_outcome=False,
            )
            child_task = await self.orchestrator.create_task(task_payload)
            self._persist_intention(run_id, intention_id, intention, str(child_task["id"]))
            if not resumed:
                goals_created += 1
                await self._emit("life.intention.started", run_id, {"intention_id": intention_id, "intention": intention.model_dump(mode="json")}, str(child_task["id"]))
            else:
                await self._emit(
                    "life.intention.updated",
                    run_id,
                    {"intention_id": intention_id, "status": "ACTIVE", "attempt": self._intention_attempts(run_id, intention_id) + 1},
                    str(child_task["id"]),
                )
            final_task = await self._pursue(child_task)
            actions = self.db.all("SELECT status FROM tool_executions WHERE task_id=?", (str(child_task["id"]),))
            action_count = len(actions)
            final_status = str(final_task.get("status", "failed"))
            fresh_evidence = self._new_verified_evidence(str(child_task["id"]), intention.evidence_refs)
            if final_status == "completed" and fresh_evidence:
                updated = self._update_intention(
                    run_id,
                    intention_id,
                    "SATISFIED",
                    evidence_refs=[*intention.evidence_refs, *fresh_evidence],
                    new_evidence_refs=fresh_evidence,
                )
                status = "completed"
                await self._emit("life.intention.satisfied", run_id, {"intention_id": intention_id, "evidence_refs": updated.evidence_refs, "new_evidence_refs": fresh_evidence}, str(child_task["id"]))
            elif final_status == "completed" and self._intention_attempts(run_id, intention_id) + 1 <= intention.cycle_budget:
                updated = self._update_intention(run_id, intention_id, "ACTIVE", reason="completed_without_new_verified_evidence")
                status = "active"
                await self._emit("life.intention.updated", run_id, {"intention_id": intention_id, "status": updated.status, "reason": updated.blocked_reason}, str(child_task["id"]))
            elif final_status in {"waiting_approval", "waiting_outcome", "paused"}:
                updated = self._update_intention(run_id, intention_id, "BLOCKED", reason=f"task_status:{final_status}")
                status = "blocked"
                await self._emit("life.intention.updated", run_id, {"intention_id": intention_id, "status": updated.status, "reason": updated.blocked_reason}, str(child_task["id"]))
            else:
                updated = self._update_intention(run_id, intention_id, "ABANDONED", reason=str(final_task.get("error") or f"task_status:{final_status}"))
                status = "abandoned"
                await self._emit("life.intention.abandoned", run_id, {"intention_id": intention_id, "reason": updated.blocked_reason}, str(child_task["id"]))
            await self._emit("life.intention.updated", run_id, {"intention_id": intention_id, "status": updated.status}, str(child_task["id"]))
            self.db.execute(
                "INSERT INTO life_cycles (id,run_id,superior_goal,cycle_index,task_id,tension_id,goal_id,intention_id,status,action_count,result_json,started_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"cycle-{uuid4()}", run_id, superior_goal, cycle_index, str(child_task["id"]), selected.tension_id, selected.id, intention_id, status, action_count, self.db.json({"task_status": final_status, "task_id": child_task["id"], "new_evidence_refs": fresh_evidence}), intention.started_at, _now()),
            )
            cycle_event = "life.cycle.retrying" if status == "active" else "life.cycle.completed"
            await self._emit(cycle_event, run_id, {"cycle_index": cycle_index, "status": status, "goal_id": selected.id, "action_count": action_count, "new_evidence_refs": fresh_evidence}, str(child_task["id"]))
            if status == "active":
                continue
            if status != "completed":
                break
            try:
                horizon = getattr(self.orchestrator, "horizon", None)
                if horizon is not None:
                    latest = horizon.latest_snapshot(final_task)
                    if latest.epistemic_state is not None:
                        state = latest.epistemic_state
            except Exception:
                pass
        summary_metrics = self._metrics_from_records(run_id)
        summary_status: Literal["completed", "blocked", "abandoned", "no_tension"] = "blocked" if status == "active" else status
        if int(summary_metrics["goals_created"]) == 0 and summary_status == "completed":
            summary_status = "no_tension"
        summary = LifeRunSummary(
            run_id=run_id,
            superior_goal=superior_goal,
            status=summary_status,
            tensions_detected=int(summary_metrics["tensions_detected"]),
            goals_created=int(summary_metrics["goals_created"]),
            goals_completed=int(summary_metrics["goals_completed"]),
            human_prompts_after_initial_goal=int(summary_metrics["human_prompts_after_initial_goal"]),
            tool_calls=int(summary_metrics["tool_calls"]),
            agc=int(summary_metrics["agc"]),
            ipr=float(summary_metrics["ipr"]),
            eggr=float(summary_metrics["eggr"]),
        )
        return summary
