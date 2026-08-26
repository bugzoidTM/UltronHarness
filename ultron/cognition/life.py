from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from ultron.cognition.self_model import EmpiricalSelfModel
from ultron.configuration import Settings
from ultron.core.events import EventBus
from ultron.db import Database
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
