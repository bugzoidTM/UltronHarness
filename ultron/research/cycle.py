"""Ciclo de experiência: memoriza lições e promove skills somente após evidência repetida."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ultron.db import Database
from ultron.learning.verified_writeback import VerifiedWritebackGate
from ultron.memory.governor import MemoryGovernor
from ultron.schemas import OutcomeResult


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SkillService:
    def __init__(self, db: Database):
        self.db = db

    def observe(
        self,
        name: str,
        trigger: list[str],
        procedure: list[str],
        success: bool,
        *,
        verification_state: str = "pending",
        verified_writeback_id: str | None = None,
    ) -> dict:
        skill = self.db.one("SELECT * FROM skills WHERE name=?", (name,))
        if skill:
            self.db.execute(
                "UPDATE skills SET success_count=success_count+?, failure_count=failure_count+?, verification_state=?, verified_writeback_id=?, updated_at=? WHERE id=?",
                (int(success), int(not success), verification_state, verified_writeback_id, utcnow(), skill["id"]),
            )
        else:
            skill_id = str(uuid4())
            self.db.execute(
                "INSERT INTO skills (id,name,description,trigger_json,procedure_json,success_count,failure_count,version,created_at,updated_at,verification_state,verified_writeback_id) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (skill_id, name, f"Candidate skill: {name}", self.db.json(trigger), self.db.json(procedure), int(success), int(not success), utcnow(), utcnow(), verification_state, verified_writeback_id),
            )
        return self.db.one("SELECT * FROM skills WHERE name=?", (name,)) or {}

    def status(self, name: str) -> str:
        item = self.db.one("SELECT success_count,failure_count,verification_state,verified_writeback_id FROM skills WHERE name=?", (name,))
        if not item:
            return "absent"
        if item["verification_state"] != "verified" or not item["verified_writeback_id"]:
            return "candidate"
        uses = int(item["success_count"]) + int(item["failure_count"])
        rate = int(item["success_count"]) / uses if uses else 0.0
        return "validated" if uses >= 3 and rate >= 0.66 else "candidate"

    def reusable_procedures(self) -> list[str]:
        rows = self.db.all("SELECT name,procedure_json FROM skills WHERE verification_state='verified' AND verified_writeback_id IS NOT NULL AND success_count+failure_count>=3 AND success_count*1.0/(success_count+failure_count)>=0.66")
        return [f"{row['name']}: {'; '.join(self.db.parse_json(row['procedure_json'], []))}" for row in rows]


class ExperienceCycle:
    """Filtro de valor: não transforma conversas triviais em memória ou skill."""

    def __init__(
        self,
        db: Database,
        skills: SkillService,
        governor: MemoryGovernor | None = None,
        *,
        minimum_authority: str = "task_registered_verifier",
    ):
        self.db, self.skills, self.governor = db, skills, governor or MemoryGovernor(db)
        self.writeback_gate = VerifiedWritebackGate(db, minimum_authority=minimum_authority)

    def consolidate(
        self,
        objective: str,
        outcome: str,
        lessons: list[str],
        success: bool,
        novel_failure: bool = False,
        outcome_result: OutcomeResult | None = None,
    ) -> dict:
        key = objective[:80].casefold().replace(" ", "_")
        skill_name = f"procedure_{key}"
        writeback = self.writeback_gate.evaluate(
            task_id=None,
            target_type="skill",
            target_id=skill_name,
            outcome_result=outcome_result,
        )
        if not writeback.allowed:
            return {
                "stored": False,
                "reason": writeback.reason,
                "verification_state": "rejected" if outcome_result and outcome_result.final else "pending",
                "outcome_authority": writeback.authority_level,
                "writeback_audit_id": writeback.audit_id,
            }
        category = "recovery" if novel_failure else "general"
        decision = self.governor.decide(category=category, verified_success=success, novel_failure=novel_failure, successful_recovery=success and novel_failure, generalizable_procedure=bool(lessons), confidence=0.8 if success else 0.6, utility_prediction=0.3 if lessons else 0.0, generalizability=0.75 if lessons else 0.35)
        if not decision.should_write:
            return {"stored": False, "reason": decision.reason, "admission": self.governor.payload(decision)}
        skill = self.skills.observe(
            skill_name,
            trigger=[objective[:120]],
            procedure=lessons or ["Repetir estratégia validada e verificar artefato."],
            success=success,
            verification_state="verified",
            verified_writeback_id=writeback.audit_id,
        )
        return {
            "stored": True,
            "skill_id": skill.get("id"),
            "skill_status": self.skills.status(skill["name"]),
            "admission": self.governor.payload(decision),
            "verification_state": "verified",
            "outcome_authority": writeback.authority_level,
            "writeback_audit_id": writeback.audit_id,
        }
