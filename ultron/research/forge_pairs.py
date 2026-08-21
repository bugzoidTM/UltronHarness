"""Calibration pareada do Project Forge com isolamento rígido do Target."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from ultron.configuration import Settings
from ultron.db import Database
from ultron.learning.experience_utility import ExperienceUtilityModel
from ultron.learning.transfer import PrivateBenchmarkRootError
from ultron.models.gateway import ModelGateway

PROMPT_VERSION = "forge-pair-v1"


@dataclass(frozen=True, slots=True)
class PairExperimentResult:
    run_id: str
    split: str
    observations: int
    mean_delta: float
    artifact_dir: Path


def _category(family: str) -> str:
    return "recovery" if family in {"dependency_recovery", "state_recovery"} else "reasoning"


def _sha256(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_commit(root: Path) -> str:
    if configured := os.getenv("ULTRON_GIT_COMMIT"):
        return configured
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


class ForgePairUtilityRunner:
    """Executa somente Calibration; Target é congelado por construção."""

    def __init__(
        self,
        settings: Settings,
        *,
        public_root: Path | None = None,
        private_root: Path | None = None,
        model_name: str = "ollama_research",
        seed: int = 42,
    ):
        self.settings = settings
        self.public_root = public_root or settings.root_dir / "benchmarks" / "forge_router_v1"
        configured = private_root or settings.private_benchmark_root
        if configured is None:
            raise PrivateBenchmarkRootError("Forge Pair Utility requer ULTRON_PRIVATE_BENCHMARK_ROOT configurado.")
        self.private_root = configured / "forge_router_v1" if not (configured / "calibration" / "answers.json").exists() else configured
        self.model_name, self.seed = model_name, seed
        self.db = Database(settings.db_path)
        self.db.initialize()
        self.models = ModelGateway(settings)

    def _tasks(self, split: str) -> list[dict]:
        tasks_path = self.public_root / split / "tasks.yaml"
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8")) or []
        if not isinstance(tasks, list):
            raise ValueError("Tarefas Forge devem ser uma lista")
        return tasks

    def _answers(self, split: str) -> dict[str, dict]:
        path = self.private_root / split / "answers.json"
        if not path.exists():
            raise PrivateBenchmarkRootError(f"Contrato Forge privado ausente: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Contrato Forge inválido")
        return payload

    @staticmethod
    def _normalise(reply: str) -> str:
        import re

        return ">".join(re.findall(r"\b[A-Z0-9]{2}\b", reply.upper().replace("→", ">")))

    @staticmethod
    def _experience(family: str) -> str:
        return {
            "structured_validation": "Valide a estrutura e suas restrições antes de aceitar ou rejeitar o resultado.",
            "dependency_recovery": "Inspecione primeiro a declaração e a resolução local antes de alterar recursos declarados.",
            "state_recovery": "Recupere somente o delta autorizado e confirme o estado final com evidência.",
            "planning": "Confirme pré-condições verificáveis antes de executar uma etapa dependente.",
            "configuration_repair": "Aplique a menor correção autorizada e valide o runtime resultante.",
        }[family]

    def _messages(self, task: dict, experience: str | None) -> list[dict[str, str]]:
        actions = "\n".join(f"{entry['code']}: {entry['description']}" for entry in task["actions"])
        prefix = experience or "Nenhuma experiência procedural está disponível."
        return [
            {"role": "system", "content": "Você executa um benchmark local. Use somente códigos disponíveis e responda apenas com a sequência de códigos solicitada."},
            {"role": "user", "content": f"Experiência procedural:\n{prefix}\n\nObjetivo: {task['objective']}\n\nAções:\n{actions}\n\nFormato: {task['response_format']}"},
        ]

    def _ensure_experience(self, family: str) -> tuple[str, str]:
        experience_id = f"forge-calibration-experience-{family}"
        existing = self.db.one("SELECT id FROM experiences WHERE id=?", (experience_id,))
        if not existing:
            now = datetime.now(UTC).isoformat()
            procedure = self._experience(family)
            self.db.execute(
                "INSERT INTO experiences (id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (experience_id, "forge-calibration-procedure", self.db.json([]), "Procedimento candidato de calibração", 1, self.db.json([]), self.db.json([procedure]), 0.8, now),
            )
            self.db.execute(
                "INSERT INTO experience_signatures (id,experience_id,category,family,domain,failure_classes_json,tool_families_json,abstraction_level,verified,historical_utility,sample_count,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"signature-{experience_id}", experience_id, _category(family), family, f"calibration_{family}", self.db.json([]), self.db.json(["benchmark.action"]), 0.9, 1, 0.0, 0, "forge_calibration", now, now),
            )
        signature = self.db.one("SELECT id FROM experience_signatures WHERE experience_id=?", (experience_id,))
        if not signature:
            raise RuntimeError("Assinatura de experiência Forge ausente")
        return experience_id, str(signature["id"])

    def _task_signature(self, task: dict) -> str:
        task_id = str(task["id"])
        signature_id = f"signature-{task_id}"
        if not self.db.one("SELECT id FROM task_signatures WHERE id=?", (signature_id,)):
            self.db.execute(
                "INSERT INTO task_signatures (id,task_id,category,family,domain,required_tools_json,uncertainty,source,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (signature_id, None, _category(str(task["family"])), str(task["family"]), str(task["target_domain"]), self.db.json(["benchmark.action"]), 0.1, "forge_calibration", datetime.now(UTC).isoformat()),
            )
        return signature_id

    async def run_calibration(self, *, limit: int | None = None) -> PairExperimentResult:
        split = "calibration"
        tasks, answers = self._tasks(split), self._answers(split)
        selected = tasks[:limit] if limit else tasks
        if not selected:
            raise ValueError("Calibration não contém tarefas")
        run_id = str(uuid4())
        artifact_dir = self.settings.artifacts_dir / "research" / "forge" / "router_calibration" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        traces: list[dict[str, object]] = []
        deltas: list[float] = []
        for task in selected:
            family = str(task["family"])
            experience_id, _ = self._ensure_experience(family)
            task_signature_id = self._task_signature(task)
            fresh = await self.models.generate(self._messages(task, None), self.model_name, seed=self.seed, max_tokens=16)
            with_experience = await self.models.generate(self._messages(task, self._experience(family)), self.model_name, seed=self.seed, max_tokens=16)
            expected = str(answers[str(task["id"])] ["expected_sequence"])
            fresh_score = float(self._normalise(fresh.content) == expected)
            experienced_score = float(self._normalise(with_experience.content) == expected)
            delta = ExperienceUtilityModel.record_pair_outcome(
                self.db,
                task_signature_id=task_signature_id,
                experience_id=experience_id,
                fresh_score=fresh_score,
                experienced_score=experienced_score,
                run_id=None,
                task_id=str(task["id"]),
                task_family=family,
                experience_family=family,
                source_domain=str(task["source_domain"]),
                target_domain=str(task["target_domain"]),
                seed=self.seed,
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                dataset_split=split,
            )
            deltas.append(delta)
            traces.append({"task_id": task["id"], "family": family, "fresh_score": fresh_score, "experienced_score": experienced_score, "paired_delta": delta, "expected_digest": _sha256(expected)})
        manifest = {
            "commit": _git_commit(self.settings.root_dir),
            "benchmark": "forge_router_v1",
            "benchmark_version": "forge-router-v1",
            "dataset_split": split,
            "model": self.model_name,
            "seed": self.seed,
            "prompt_version": PROMPT_VERSION,
            "config_hash": _sha256(self.settings.raw),
            "hardware": {"platform": platform.platform()},
            "target_mutation_forbidden": True,
        }
        payload = {"manifest": manifest, "observations": len(traces), "mean_delta": round(sum(deltas) / len(deltas), 6), "traces": traces}
        (artifact_dir / "pair_utility.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return PairExperimentResult(run_id, split, len(traces), payload["mean_delta"], artifact_dir)

    async def run_target(self) -> None:
        raise RuntimeError("Target Forge é avaliação congelada; Pair Utility só pode ser gravada durante Calibration.")

    def run(self, *, limit: int | None = None) -> PairExperimentResult:
        return asyncio.run(self.run_calibration(limit=limit))
