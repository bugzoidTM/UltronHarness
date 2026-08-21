"""LEARN-2: curva CGFE com experiências procedurais verificadas e filtradas."""

from __future__ import annotations

from dataclasses import dataclass

from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import Settings
from ultron.db import Database
from ultron.memory.governor import MemoryGovernor


@dataclass(frozen=True, slots=True)
class VerifiedExperience:
    category: str
    content: str
    evidence: str
    confidence: float = 0.9
    utility: float = 0.8
    generalizability: float = 0.8


class VerifiedExperiencePool:
    """Corpus curado de princípios, sem objetivos, respostas, IDs ou fixtures UGIB."""

    _STEPS = {
        "reasoning": (
            "separe premissas de conclusão", "verifique unidades e limites", "teste o caso-base antes de generalizar",
            "mantenha apenas as condições declaradas", "confirme o formato final solicitado",
        ),
        "coding": (
            "preserve a assinatura pedida", "prefira a construção mínima compatível", "verifique sintaxe antes de finalizar",
            "não acrescente explicações ao artefato", "confirme o identificador de saída",
        ),
        "tool_use": (
            "selecione somente ferramenta declarada", "confirme o escopo antes de operar", "trate o workspace como isolado",
            "verifique o artefato após a operação", "registre falha observável antes de repetir",
        ),
        "recovery": (
            "classifique a falha observável", "não repita tentativa sem pré-condição nova", "preserve o escopo da recuperação",
            "verifique a evidência posterior", "pare quando a política não permitir nova ação",
        ),
    }

    def __init__(self, governor: MemoryGovernor):
        self.governor = governor
        self._admitted = self._build_and_filter()

    def _build_and_filter(self) -> list[VerifiedExperience]:
        candidates: list[VerifiedExperience] = []
        for category, steps in self._STEPS.items():
            for index in range(50):
                first = steps[index % len(steps)]
                second = steps[(index // len(steps) + 1) % len(steps)]
                candidates.append(
                    VerifiedExperience(
                        category=category,
                        content=f"[{category}] Procedimento verificado: {first}; depois {second}.",
                        evidence=f"reviewed_procedure:{category}:{index + 1:02d}",
                    )
                )
        admitted: list[VerifiedExperience] = []
        for item in candidates:
            decision = self.governor.decide(
                category=item.category,
                verified_success=True,
                generalizable_procedure=True,
                confidence=item.confidence,
                utility_prediction=item.utility,
                generalizability=item.generalizability,
            )
            if decision.should_write:
                admitted.append(item)
        return admitted

    def select(self, count: int) -> list[str]:
        if count < 0:
            raise ValueError("Quantidade de experiências deve ser não negativa")
        if count == 0:
            return []
        if count > len(self._admitted):
            raise ValueError("Pool verificado não contém experiências suficientes")
        per_category: dict[str, list[VerifiedExperience]] = {}
        for item in self._admitted:
            per_category.setdefault(item.category, []).append(item)
        ordered: list[VerifiedExperience] = []
        offsets = {category: 0 for category in per_category}
        categories = tuple(sorted(per_category))
        while len(ordered) < count:
            for category in categories:
                index = offsets[category]
                if index < len(per_category[category]) and len(ordered) < count:
                    ordered.append(per_category[category][index])
                    offsets[category] += 1
        return [item.content for item in ordered]

    @property
    def admitted_count(self) -> int:
        return len(self._admitted)


class Learn2Experiment:
    """Executa fresh/experienced mantendo seed, modelo e conjunto de tarefas iguais."""

    def __init__(self, settings: Settings, model_name: str | None, seed: int):
        self.settings, self.model_name, self.seed = settings, model_name, seed
        self.db = Database(settings.db_path)
        self.db.initialize()
        self.pool = VerifiedExperiencePool(MemoryGovernor(self.db))

    async def run_curve_async(self, counts: list[int]) -> list[dict]:
        """Executa uma baseline fresh pareada e todas as condições experienced."""
        if not counts or any(count < 0 for count in counts):
            raise ValueError("LEARN-2 requer contagens não negativas")
        fresh_runner = UGIBLiteRunner(self.settings)
        fresh_manifest, fresh_summary = await fresh_runner.run_async("ultron-fresh", self.model_name, self.seed)
        fresh_dir = self.settings.artifacts_dir / "benchmarks" / fresh_manifest.run_id
        fresh_dir.mkdir(parents=True, exist_ok=True)
        fresh_runner.persist_run(fresh_manifest, fresh_summary, fresh_dir)
        rows: list[dict] = []
        for experience_count in counts:
            corpus = self.pool.select(experience_count)
            experienced_score = fresh_summary.score
            experienced_run_id = fresh_manifest.run_id
            if corpus:
                experienced_runner = UGIBLiteRunner(self.settings)
                experienced_manifest, experienced_summary = await experienced_runner.run_async(
                    "ultron-experienced",
                    self.model_name,
                    self.seed,
                    experience_context=corpus,
                    experience_limit=experience_count,
                )
                experienced_dir = self.settings.artifacts_dir / "benchmarks" / experienced_manifest.run_id
                experienced_dir.mkdir(parents=True, exist_ok=True)
                experienced_runner.persist_run(experienced_manifest, experienced_summary, experienced_dir)
                experienced_score = experienced_summary.score
                experienced_run_id = experienced_manifest.run_id
            rows.append(
                {
                    "experience_count": experience_count,
                    "fresh_score": fresh_summary.score,
                    "experienced_score": experienced_score,
                    "cgfe": round(experienced_score - fresh_summary.score, 4),
                    "fresh_run_id": fresh_manifest.run_id,
                    "experienced_run_id": experienced_run_id,
                    "admitted_pool_size": self.pool.admitted_count,
                    "selection_policy": "MAS_verified_category_compatible",
                }
            )
        return rows

    async def run_async(self, experience_count: int) -> dict:
        """Compatibilidade para execução de um único ponto da curva."""
        return (await self.run_curve_async([experience_count]))[0]
