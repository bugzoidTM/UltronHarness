"""Snapshot e avaliação Target congelada do Router Learning Forge."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from uuid import uuid4

from ultron.learning.negative_transfer import FamilyUtilityState, NegativeTransferFirewall
from ultron.research.forge_pairs import ForgePairUtilityRunner, _sha256

CONDITIONS = ("never_inject", "always_inject", "router_use_abstain_reject")


@dataclass(frozen=True, slots=True)
class RouterSnapshot:
    snapshot_id: str
    payload: dict[str, object]
    path: Path
    digest: str


class FrozenForgeRouter:
    """Aplica exclusivamente o estado serializado na Calibration."""

    def __init__(self, snapshot: RouterSnapshot):
        self.snapshot = snapshot
        rows = snapshot.payload["family_utility_map"]
        self.family_map = {
            (str(row["task_family"]), str(row["experience_family"])): str(row["state"])
            for row in rows
        }

    def decision(self, family: str) -> str:
        state = self.family_map.get((family, family), FamilyUtilityState.INSUFFICIENT_DATA.value)
        return "USE" if state == FamilyUtilityState.PROMOTABLE.value else "ABSTAIN"


class ForgeRouterLearning:
    def __init__(self, pair_runner: ForgePairUtilityRunner):
        self.pairs = pair_runner
        self.db = pair_runner.db

    def _calibration_rows(self) -> list[dict]:
        return self.db.all(
            "SELECT DISTINCT task_family, experience_family FROM experience_pair_utility WHERE dataset_split='calibration'"
        )

    def freeze(self) -> RouterSnapshot:
        for row in self._calibration_rows():
            NegativeTransferFirewall.recalculate(self.db, str(row["task_family"]), str(row["experience_family"]))
        family_map = self.db.all(
            "SELECT task_family,experience_family,mean_delta,sample_count,ci95_low,ci95_high,state FROM family_utility_map ORDER BY task_family,experience_family"
        )
        experiences = self.db.all(
            "SELECT es.experience_id,es.family,es.domain,es.verified FROM experience_signatures es WHERE es.source='forge_calibration' ORDER BY es.experience_id"
        )
        utility_rows = self.db.all(
            "SELECT experience_id,task_id,task_family,experience_family,source_domain,target_domain,paired_delta,seed,model_name,prompt_version FROM experience_pair_utility WHERE dataset_split='calibration' ORDER BY id"
        )
        payload: dict[str, object] = {
            "snapshot_version": "forge-router-v1",
            "family_utility_map": family_map,
            "thresholds": {
                "min_samples": NegativeTransferFirewall.min_samples,
                "promotable_threshold": NegativeTransferFirewall.promotable_threshold,
                "harmful_threshold": NegativeTransferFirewall.harmful_threshold,
            },
            "eligible_experiences": experiences,
            "utility_table_hash": _sha256(utility_rows),
            "experience_corpus_hash": _sha256(experiences),
            "model": self.pairs.model_name,
            "benchmark_version": "forge-router-v1",
            "commit": "configured-at-run-time",
        }
        snapshot_id = str(uuid4())
        destination = self.pairs.settings.artifacts_dir / "research" / "forge" / "router_calibration" / snapshot_id
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "router_snapshot.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return RouterSnapshot(snapshot_id, payload, path, _sha256(payload))

    @staticmethod
    def load(path: Path) -> RouterSnapshot:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RouterSnapshot(path.parent.name, payload, path, _sha256(payload))

    async def evaluate_target(
        self,
        snapshot: RouterSnapshot,
        *,
        limit: int | None = None,
    ) -> dict[str, object]:
        tasks = self.pairs._tasks("target")
        answers = self.pairs._answers("target")
        selected = tasks[:limit] if limit else tasks
        before = {
            "utility_table_hash": _sha256(
                self.db.all("SELECT experience_id,task_id,paired_delta FROM experience_pair_utility WHERE dataset_split='calibration' ORDER BY id")
            ),
            "family_map_hash": _sha256(self.db.all("SELECT * FROM family_utility_map ORDER BY task_family,experience_family")),
        }
        frozen = FrozenForgeRouter(snapshot)
        ordered = list(CONDITIONS)
        random.Random(self.pairs.seed).shuffle(ordered)
        runs: dict[str, list[dict[str, object]]] = {condition: [] for condition in CONDITIONS}
        fresh_success: dict[str, bool] = {}
        for condition in ordered:
            for task in selected:
                family = str(task["family"])
                decision = "NOT_EVALUATED"
                experience: str | None = None
                if condition == "always_inject":
                    experience, decision = self.pairs._experience(family), "USE"
                elif condition == "router_use_abstain_reject":
                    decision = frozen.decision(family)
                    experience = self.pairs._experience(family) if decision == "USE" else None
                response = await self.pairs.models.generate(
                    self.pairs._messages(task, experience),
                    self.pairs.model_name,
                    seed=self.pairs.seed,
                    max_tokens=16,
                )
                expected = str(answers[str(task["id"])] ["expected_sequence"])
                success = self.pairs._normalise(response.content) == expected
                if condition == "never_inject":
                    fresh_success[str(task["id"])] = success
                runs[condition].append(
                    {
                        "task_id": task["id"],
                        "family": family,
                        "variant": task.get("lexical_variant"),
                        "success": success,
                        "injected": experience is not None,
                        "decision": decision,
                        "expected_digest": _sha256(expected),
                    }
                )
        after = {
            "utility_table_hash": _sha256(
                self.db.all("SELECT experience_id,task_id,paired_delta FROM experience_pair_utility WHERE dataset_split='calibration' ORDER BY id")
            ),
            "family_map_hash": _sha256(self.db.all("SELECT * FROM family_utility_map ORDER BY task_family,experience_family")),
        }
        if before != after:
            raise RuntimeError("Target alterou estado de Calibration; avaliação inválida.")
        scores = {condition: round(mean(float(item["success"]) for item in traces), 6) for condition, traces in runs.items()}
        harmful = {}
        for condition, traces in runs.items():
            injected = [item for item in traces if item["injected"]]
            harmful[condition] = round(
                sum(bool(fresh_success.get(str(item["task_id"]))) and not bool(item["success"]) for item in injected) / len(injected),
                6,
            ) if injected else 0.0
        result = {
            "benchmark": "forge_router_v1",
            "dataset_split": "target",
            "snapshot_hash": snapshot.digest,
            "snapshot_path": str(snapshot.path),
            "condition_order": ordered,
            "scores": scores,
            "stg": round(scores["router_use_abstain_reject"] - max(scores["never_inject"], scores["always_inject"]), 6),
            "router_vs_never": round(scores["router_use_abstain_reject"] - scores["never_inject"], 6),
            "router_vs_always": round(scores["router_use_abstain_reject"] - scores["always_inject"], 6),
            "harmful_retrieval_rate": harmful,
            "freeze_proof": {"before": before, "after": after, "identical": before == after},
            "traces": runs,
        }
        destination = self.pairs.settings.artifacts_dir / "research" / "forge" / "router_target" / str(uuid4())
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "target_evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def evaluate(self, snapshot: RouterSnapshot, *, limit: int | None = None) -> dict[str, object]:
        return asyncio.run(self.evaluate_target(snapshot, limit=limit))
