"""Ciclo de experiência: memoriza lições e promove skills somente após evidência repetida."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ultron.db import Database
from ultron.memory.governor import MemoryGovernor


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SkillService:
    def __init__(self, db: Database):
        self.db = db

    def observe(self, name: str, trigger: list[str], procedure: list[str], success: bool) -> dict:
        skill = self.db.one("SELECT * FROM skills WHERE name=?", (name,))
        if skill:
            self.db.execute(
                "UPDATE skills SET success_count=success_count+?, failure_count=failure_count+?, updated_at=? WHERE id=?",
                (int(success), int(not success), utcnow(), skill["id"]),
            )
        else:
            skill_id = str(uuid4())
            self.db.execute(
                "INSERT INTO skills (id,name,description,trigger_json,procedure_json,success_count,failure_count,version,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (skill_id, name, f"Candidate skill: {name}", self.db.json(trigger), self.db.json(procedure), int(success), int(not success), utcnow(), utcnow()),
            )
        return self.db.one("SELECT * FROM skills WHERE name=?", (name,)) or {}

    def status(self, name: str) -> str:
        item = self.db.one("SELECT success_count,failure_count FROM skills WHERE name=?", (name,))
        if not item:
            return "absent"
        uses = int(item["success_count"]) + int(item["failure_count"])
        rate = int(item["success_count"]) / uses if uses else 0.0
        return "validated" if uses >= 3 and rate >= 0.66 else "candidate"

    def reusable_procedures(self) -> list[str]:
        rows = self.db.all("SELECT name,procedure_json FROM skills WHERE success_count+failure_count>=3 AND success_count*1.0/(success_count+failure_count)>=0.66")
        return [f"{row['name']}: {'; '.join(self.db.parse_json(row['procedure_json'], []))}" for row in rows]


class ExperienceCycle:
    """Filtro de valor: não transforma conversas triviais em memória ou skill."""

    def __init__(self, db: Database, skills: SkillService, governor: MemoryGovernor | None = None):
        self.db, self.skills, self.governor = db, skills, governor or MemoryGovernor(db)

    def consolidate(self, objective: str, outcome: str, lessons: list[str], success: bool, novel_failure: bool = False) -> dict:
        category = "recovery" if novel_failure else "general"
        decision = self.governor.decide(category=category, verified_success=success, novel_failure=novel_failure, successful_recovery=success and novel_failure, generalizable_procedure=bool(lessons), confidence=0.8 if success else 0.6, utility_prediction=0.3 if lessons else 0.0, generalizability=0.75 if lessons else 0.35)
        if not decision.should_write:
            return {"stored": False, "reason": decision.reason, "admission": self.governor.payload(decision)}
        key = objective[:80].casefold().replace(" ", "_")
        skill = self.skills.observe(
            f"procedure_{key}",
            trigger=[objective[:120]],
            procedure=lessons or ["Repetir estratégia validada e verificar artefato."],
            success=success,
        )
        return {"stored": True, "skill_id": skill.get("id"), "skill_status": self.skills.status(skill["name"]), "admission": self.governor.payload(decision)}
