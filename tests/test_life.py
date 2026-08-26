from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from ultron.cognition.epistemic import initial_state, record_unknown
from ultron.cognition.life import LifeAgencyController
from ultron.configuration import Settings, load_settings
from ultron.core.events import EventBus
from ultron.core.orchestrator import Orchestrator
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.models.gateway import ModelGateway
from ultron.policy.engine import PolicyEngine
from ultron.schemas import CognitiveTension, EpistemicState, PersistentIntention, TaskCreate
from ultron.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def _runtime(tmp_path: Path, *, life_enabled: bool = True) -> tuple[Settings, Database, Orchestrator, LifeAgencyController]:
    raw = deepcopy(load_settings(ROOT).raw)
    raw["models"]["primary"] = "local-fallback"
    raw["memory"]["vector_enabled"] = False
    raw["cognition"]["controller_mode"] = "full_plan"
    raw["cognition"]["feature_flags"]["epistemic_state"] = True
    raw["life"] = {
        "enabled": life_enabled,
        "max_goals": 2,
        "max_candidates": 3,
        "max_actions_per_goal": 2,
        "competence_min_sample": 2,
        "competence_max_success_rate": 0.5,
        "feature_flags": {
            "tension_detection": life_enabled,
            "goal_selection": life_enabled,
            "intention_persistence": life_enabled,
            "autonomous_continuation": life_enabled,
        },
        "goal_value_weights": {
            "expected_information_gain": 0.30,
            "expected_capability_gain": 0.30,
            "importance": 0.20,
            "tractability": 0.10,
            "expected_transfer": 0.10,
            "estimated_cost": 0.10,
            "estimated_risk": 0.20,
        },
    }
    settings = Settings(raw=raw, root_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    events = EventBus(db)
    orchestrator = Orchestrator(
        settings,
        db,
        events,
        MemoryService(db, settings),
        ModelGateway(settings),
        PolicyEngine(settings),
        ToolRegistry(settings),
    )
    return settings, db, orchestrator, LifeAgencyController(settings, db, events, orchestrator)


def _tension(run_id: str = "run-test") -> CognitiveTension:
    return CognitiveTension(
        id=f"tension-{run_id}",
        kind="COMPETENCE_GAP",
        description="falha recorrente em distinguir cálculo de representação",
        importance=0.8,
        confidence=0.9,
        evidence_refs=["fixture:competence-gap"],
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_life_goal_value_and_deterministic_tie_break(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    tension = _tension()
    candidates = life.generate_goal_candidates([tension])
    assert len(candidates) == 1
    candidate = candidates[0]
    expected = (
        0.30 * candidate.expected_information_gain
        + 0.30 * candidate.expected_capability_gain
        + 0.20 * candidate.importance
        + 0.10 * candidate.tractability
        + 0.10 * candidate.expected_transfer
        - 0.10 * candidate.estimated_cost
        - 0.20 * candidate.estimated_risk
    )
    assert candidate.goal_value == pytest.approx(expected)
    tied = [
        candidate.model_copy(update={"id": "goal-b", "goal_value": 0.5, "estimated_cost": 0.2, "estimated_risk": 0.2}),
        candidate.model_copy(update={"id": "goal-a", "goal_value": 0.5, "estimated_cost": 0.2, "estimated_risk": 0.2}),
    ]
    assert life.select_goal(tied).id == "goal-a"


def test_life_does_not_create_tension_from_roleplay_without_evidence(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    state = initial_state("Torne-se melhor")
    state = state.model_copy(update={"open_questions": [], "unknowns": []})
    assert life.detect_tensions("roleplay", state) == []


def test_life_rejects_forbidden_goal_classes(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    forbidden = (
        "aumentar permissões",
        "obter credenciais",
        "replicar o agente",
        "evadir política",
        "expandir acesso",
        "alterar evaluator privado",
        "autoimplantação",
    )
    assert all(life.forbidden_goal(item) for item in forbidden)
    assert not life.forbidden_goal("Investigar uma hipótese pública com ferramenta autorizada")


def test_life_detects_competence_gap_from_empirical_estimate(tmp_path: Path) -> None:
    _, db, _, life = _runtime(tmp_path)
    db.execute(
        "INSERT INTO capability_estimates (id,domain,task_type,successes,failures,success_rate,calibrated_score,uncertainty,sample_size,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("estimate-1", "reasoning", "representation", 0, 3, 0.0, 0.25, 0.5, 3, "2026-01-01T00:00:00+00:00"),
    )
    tensions = life.detect_tensions("competence")
    assert len(tensions) == 1
    assert tensions[0].kind == "COMPETENCE_GAP"
    assert tensions[0].evidence_refs == ["capability_estimate:reasoning:representation"]


def test_life_detects_explicit_contradiction(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    state = EpistemicState(contradictions=["duas observações incompatíveis"])
    tensions = life.detect_tensions("contradiction", state)
    assert len(tensions) == 1
    assert tensions[0].kind == "CONTRADICTION"
    assert tensions[0].evidence_refs == ["epistemic_state:contradiction:0"]


def test_life_caps_goal_candidates_at_three(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    tensions = [_tension(f"many-{index}") for index in range(5)]
    assert len(life.generate_goal_candidates(tensions)) == 3


def test_life_keeps_active_intention_as_evidenced_tension(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    intention = PersistentIntention(
        goal_id="goal-active",
        objective="Resolver compromisso verificável",
        status="ACTIVE",
        started_at="2026-01-01T00:00:00+00:00",
        cycle_budget=2,
        evidence_refs=["fixture:commitment"],
    )
    life._persist_intention("commitment", "intention-1", intention, None)
    tensions = life.detect_tensions("commitment")
    assert len(tensions) == 1
    assert tensions[0].kind == "UNFINISHED_COMMITMENT"
    assert "life_intention:intention-1" in tensions[0].evidence_refs


def test_life_tension_requires_evidence_reference(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    state = record_unknown(EpistemicState(), "necessidade de investigar", evidence_ref=None)
    assert life.detect_tensions("no-evidence", state) == []
    state = record_unknown(EpistemicState(), "necessidade de investigar", evidence_ref="fixture:unknown")
    tensions = life.detect_tensions("with-evidence", state)
    assert len(tensions) == 1
    assert tensions[0].kind == "UNKNOWN_IMPORTANT"


@pytest.mark.asyncio
async def test_life_two_autonomous_goal_cycles(tmp_path: Path) -> None:
    _, db, _, life = _runtime(tmp_path)
    state = record_unknown(
        initial_state("Torne-se progressivamente mais capaz"),
        "distinguir erro de cálculo de erro de representação",
        evidence_ref="fixture:competence-gap",
    )
    summary = await life.run(
        "Torne-se progressivamente mais capaz de resolver problemas inéditos.",
        workspace="life",
        initial_state=state,
    )
    assert summary.human_prompts_after_initial_goal == 0
    assert summary.goals_created == 1
    assert summary.goals_completed == 0
    assert summary.tool_calls == 0
    assert summary.agc == 0
    assert summary.ipr == pytest.approx(0.0)
    assert summary.eggr == pytest.approx(0.0)
    assert db.one("SELECT COUNT(*) AS count FROM life_cycles WHERE run_id=?", (summary.run_id,))["count"] == 2
    assert db.one("SELECT COUNT(*) AS count FROM life_intentions WHERE run_id=?", (summary.run_id,))["count"] == 1
    events = db.all("SELECT event_type,payload_json FROM events WHERE payload_json LIKE ?", (f'%{summary.run_id}%',))
    event_types = {row["event_type"] for row in events}
    assert {
        "life.tension.detected",
        "life.goal_candidates.generated",
        "life.goal.selected",
        "life.intention.started",
        "life.intention.updated",
        "life.cycle.retrying",
    } <= event_types


def test_life_ablation_disables_autonomous_continuation(tmp_path: Path) -> None:
    _, _, _, life = _runtime(tmp_path)
    life.config["feature_flags"]["autonomous_continuation"] = False
    state = record_unknown(EpistemicState(), "lacuna evidenciada", evidence_ref="fixture:gap")
    tensions = life.detect_tensions("ablation", state)
    candidates = life.generate_goal_candidates(tensions)
    assert life.select_goal(candidates) is not None
    assert life._enabled("autonomous_continuation") is False


def test_life_inspect_returns_sanitized_persistent_rows(tmp_path: Path) -> None:
    _, db, _, life = _runtime(tmp_path)
    tension = _tension("inspect")
    life._persist_tension("inspect", tension)
    life._persist_candidate("inspect", life.generate_goal_candidates([tension])[0])
    result = life.inspect("inspect")
    assert result is not None
    assert result["tensions"][0]["evidence_refs"] == ["fixture:competence-gap"]
    assert "evidence_refs_json" not in result["tensions"][0]
    assert result["candidates"][0]["selected"] is False


class _AuthenticFakeOrchestrator:
    def __init__(self, db: Database):
        self.db = db
        self.tasks: dict[str, dict[str, str]] = {}
        self.create_count = 0

    async def create_task(self, payload) -> dict[str, str]:
        self.create_count += 1
        task_id = f"fake-task-{self.create_count}"
        task = {"id": task_id, "status": "created", "objective": payload.objective}
        self.tasks[task_id] = task
        return task

    async def run(self, task_id: str) -> None:
        attempt = int(task_id.rsplit("-", 1)[-1])
        action_id = f"{task_id}-action"
        self.db.execute(
            "INSERT INTO cognitive_actions (id,action_id,task_id,iteration,tool,arguments_json,expected_evidence_json,status,created_at,executed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"row-{action_id}", action_id, task_id, 1, "fixture.observe", "{}", "{}", "completed", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"),
        )
        self.db.execute(
            "INSERT INTO tool_executions (id,task_id,tool_name,arguments_json,status,risk,output,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"tool-{task_id}", task_id, "fixture.observe", "{}", "completed", "R0", "deterministic observation", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"),
        )
        if attempt % 2 == 0:
            prediction_id = f"prediction-{task_id}"
            self.db.execute(
                "INSERT INTO cognitive_predictions (id,prediction_id,task_id,action_id,iteration,hypothesis,expected_observation,confidence_before,action_json,predicted_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"row-{prediction_id}", prediction_id, task_id, action_id, 1, "a hipótese da fixture será confirmada", "observação verificável", 0.8, "{}", "2026-01-01T00:00:00+00:00"),
            )
            self.db.execute(
                "INSERT INTO prediction_observations (id,prediction_id,task_id,action_id,observed_output,result_status,verification_passed,confidence_after,classification,evidence_refs_json,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"observation-{task_id}", prediction_id, task_id, action_id, "resultado contradiz a previsão", "completed", 1, 0.1, "reject", self.db.json([f"fixture:prediction-error:{task_id}"]), "2026-01-01T00:00:02+00:00"),
            )
        self.tasks[task_id]["status"] = "completed"

    def get_task(self, task_id: str) -> dict[str, str] | None:
        return self.tasks.get(task_id)


@pytest.mark.asyncio
async def test_life_authentic_agency_uses_new_prediction_error_for_second_goal(tmp_path: Path) -> None:
    settings, db, _, life = _runtime(tmp_path)
    fake = _AuthenticFakeOrchestrator(db)
    life.orchestrator = fake
    state = record_unknown(EpistemicState(), "lacuna inicial verificável", evidence_ref="fixture:unknown-A")

    summary = await life.run("Melhorar a resolução de problemas", initial_state=state)

    assert summary.goals_created == 2
    assert summary.goals_completed == 2
    assert summary.agc == 1
    assert summary.human_prompts_after_initial_goal == 0
    assert summary.tool_calls == 4
    assert summary.ipr == pytest.approx(1.0)
    assert summary.eggr == pytest.approx(1.0)
    assert db.one("SELECT COUNT(DISTINCT goal_id) AS count FROM life_cycles WHERE run_id=?", (summary.run_id,))["count"] == 2
    assert db.one("SELECT COUNT(*) AS count FROM life_cycles WHERE run_id=? AND status='active'", (summary.run_id,))["count"] == 2
    tensions = db.all("SELECT kind,description FROM life_tensions WHERE run_id=? ORDER BY created_at", (summary.run_id,))
    assert {row["kind"] for row in tensions} == {"UNKNOWN_IMPORTANT", "UNFINISHED_COMMITMENT", "PREDICTION_ERROR"}
    assert any(row["kind"] == "PREDICTION_ERROR" for row in tensions)
    assert all("Verificar a transferência" not in row["description"] for row in tensions)


def test_life_sources_are_scoped_to_run_provenance(tmp_path: Path) -> None:
    _, db, orchestrator, life = _runtime(tmp_path)
    old_intention = PersistentIntention(
        goal_id="old-goal",
        objective="Compromisso de outro run",
        status="ACTIVE",
        started_at="2026-01-01T00:00:00+00:00",
        cycle_budget=2,
        evidence_refs=["fixture:old-run"],
    )
    life._persist_intention("old-run", "old-intention", old_intention, None)
    assert life.detect_tensions("new-run") == []

    task = asyncio.run(orchestrator.create_task(TaskCreate(title="fixture", objective="fixture", workspace="life")))
    task_id = str(task["id"])
    action_id = f"{task_id}-action"
    db.execute(
        "INSERT INTO cognitive_actions (id,action_id,task_id,iteration,tool,arguments_json,expected_evidence_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"row-{action_id}", action_id, task_id, 1, "fixture.observe", "{}", "{}", "completed", "2026-01-01T00:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO cognitive_predictions (id,prediction_id,task_id,action_id,iteration,hypothesis,expected_observation,confidence_before,action_json,predicted_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("prediction-row", "prediction-old", task_id, action_id, 1, "hipótese", "observação", 0.8, "{}", "2026-01-01T00:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO prediction_observations (id,prediction_id,task_id,action_id,observed_output,result_status,verification_passed,confidence_after,classification,evidence_refs_json,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("observation-row", "prediction-old", task_id, action_id, "erro", "completed", 1, 0.1, "reject", db.json(["fixture:old-prediction"]), "2026-01-01T00:00:02+00:00"),
    )
    current_intention = PersistentIntention(
        goal_id="current-goal",
        objective="Compromisso deste run",
        status="ACTIVE",
        started_at="2026-01-01T00:00:00+00:00",
        cycle_budget=2,
        evidence_refs=["fixture:current-run"],
    )
    life._persist_intention("current-run", "current-intention", current_intention, task_id)
    assert life.detect_tensions("other-run") == []
    assert any(item.kind == "PREDICTION_ERROR" for item in life.detect_tensions("current-run"))


def test_life_new_verified_evidence_is_required_for_satisfaction(tmp_path: Path) -> None:
    _, db, _, life = _runtime(tmp_path)
    tension = _tension("evidence")
    life._persist_tension("evidence", tension)
    candidate = life.generate_goal_candidates([tension])[0]
    life._persist_candidate("evidence", candidate, selected=True)
    intention = PersistentIntention(
        goal_id=candidate.id,
        objective=candidate.objective,
        status="ACTIVE",
        started_at="2026-01-01T00:00:00+00:00",
        cycle_budget=2,
        evidence_refs=tension.evidence_refs,
    )
    life._persist_intention("evidence", "intention-evidence", intention, "task-no-evidence")
    assert life._new_verified_evidence("task-no-evidence", intention.evidence_refs) == []
    assert db.one("SELECT new_evidence_refs_json FROM life_intentions WHERE id=?", ("intention-evidence",))["new_evidence_refs_json"] == "[]"
