"""Harnesses determinísticos de transferência procedural, sem vazamento alvo–origem.

O protocolo histórico compara fresh e experienced. O Transfer-100 v3 acrescenta
uma ablação por tarefa entre Never, Always e o roteador Hermes USE/ABSTAIN/REJECT.
Contratos do v3 são externos ao repositório e não entram no contexto do modelo.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import yaml

from ultron.cognition.task_signature import TaskSignatureClassifier
from ultron.configuration import Settings
from ultron.db import Database
from ultron.learning.experience_signature import ExperienceSignature
from ultron.learning.routing_service import ShadowExperienceRoutingService
from ultron.models.gateway import ModelGateway

InjectionCondition = Literal["never_inject", "always_inject", "router_use_abstain_reject"]
ROUTING_CONDITIONS: tuple[InjectionCondition, ...] = (
    "never_inject",
    "always_inject",
    "router_use_abstain_reject",
)


class TransferDataset:
    """Carrega tarefas públicas e contratos privados de raízes separadas."""

    def __init__(self, root: Path, contract_root: Path | None = None):
        self.root = root
        # Compatibilidade retroativa: benchmarks anteriores mantêm contratos no root.
        self.contract_root = contract_root or root

    def public_tasks(self) -> list[dict]:
        tasks = yaml.safe_load((self.root / "tasks.yaml").read_text(encoding="utf-8")) or []
        if not isinstance(tasks, list):
            raise ValueError("tasks.yaml deve conter uma lista")
        return tasks

    def private_answers(self) -> dict[str, dict]:
        answers_path = self.contract_root / "answers.json"
        if not answers_path.exists():
            raise FileNotFoundError(f"Contrato privado ausente: {answers_path}")
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
        if not isinstance(answers, dict):
            raise ValueError("answers.json deve conter um objeto")
        return answers

    def assert_isolated(self, experience_corpus: list[str]) -> None:
        """Rejeita corpus que replique texto público, resposta ou fixture privada."""
        public = "\n".join(
            "\n".join(str(value) for value in task.values()) for task in self.public_tasks()
        ).casefold()
        private = (self.contract_root / "answers.json").read_text(encoding="utf-8").casefold()
        fixtures_path = self.contract_root / "fixtures.json"
        fixtures = fixtures_path.read_text(encoding="utf-8").casefold() if fixtures_path.exists() else ""
        for item in experience_corpus:
            candidate = item.strip().casefold()
            if candidate and (candidate in public or candidate in private or candidate in fixtures):
                raise RuntimeError("Data leakage detectado no corpus de transferência")

    def families(self) -> set[str]:
        return {str(task["family"]) for task in self.public_tasks()}


class TransferExperiment:
    """Compara execução fresh e experienced, por tarefa ou em lote por família."""

    ORIGIN_CORPUS = {
        "structured_validation": [
            "Para validar dados estruturados, primeiro confirme que a entrada pode ser lida, depois valide campos obrigatórios e tipos, e só então aceite o resultado."
        ],
        "dependency_recovery": [
            "Para recuperar uma dependência, primeiro identifique a declaração de estado, depois restaure somente o recurso declarado e por fim execute uma verificação de resolução."
        ],
        "state_recovery": [
            "Para recuperar estado, primeiro inspecione a situação atual, preserve o escopo da alteração, aplique apenas a reversão autorizada e confirme o estado final."
        ],
        "planning": [
            "Para planejar etapas dependentes, ordene as pré-condições antes dos dependentes, bloqueie a execução sem evidência da pré-condição e valide a conclusão de cada etapa."
        ],
        "configuration_repair": [
            "Para reparar configuração, inspecione estrutura e valores, aplique somente a mudança autorizada e valide o resultado antes de concluir."
        ],
    }

    def __init__(
        self,
        settings: Settings,
        model_name: str = "ollama_research",
        seed: int = 42,
        benchmark_name: str = "transfer20",
        origin_corpus: dict[str, list[str]] | None = None,
        batch_by_family: bool = False,
        batch_size: int = 5,
        contract_root: Path | None = None,
    ):
        self.settings, self.model_name, self.seed = settings, model_name, seed
        self.benchmark_name = benchmark_name
        self.origin_corpus = origin_corpus or self.ORIGIN_CORPUS
        self.batch_by_family = batch_by_family
        self.batch_size = max(1, batch_size)
        self.dataset = TransferDataset(settings.root_dir / "benchmarks" / benchmark_name, contract_root)
        self.db, self.models = Database(settings.db_path), ModelGateway(settings)
        self.db.initialize()

    @staticmethod
    def _normalise_plan(reply: str) -> str:
        clean = reply.upper().replace("→", ">")
        return ">".join(re.findall(r"\b[A-Z]{1,3}\d?\b", clean))

    def _messages(self, task: dict, procedures: list[str]) -> list[dict[str, str]]:
        procedure_block = "\n".join(f"- {item}" for item in procedures) or "- Nenhuma experiência prévia disponível."
        action_lines = "\n".join(f"{action['code']}: {action['description']}" for action in task["actions"])
        return [
            {"role": "system", "content": "Você é um executor local de benchmark. Não use internet e não exponha raciocínio privado. Escolha apenas códigos que aparecem no caso e entregue somente a sequência pedida."},
            {"role": "user", "content": f"Experiência procedural disponível:\n{procedure_block}\n\nCaso alvo ({task['target_domain']}):\n{task['objective']}\n\nAções disponíveis:\n{action_lines}\n\nFormato obrigatório: {task['response_format']}"},
        ]

    def _batch_messages(self, tasks: list[dict], procedures: list[str]) -> list[dict[str, str]]:
        procedure_block = "\n".join(f"- {item}" for item in procedures) or "- Nenhuma experiência prévia disponível."
        actions = "; ".join(f"{item['code']}: {item['description']}" for item in tasks[0]["actions"])
        cases = [f"{task['id']} | {task['objective']}" for task in tasks]
        return [
            {"role": "system", "content": "Executor local de benchmark. Não use internet nem exponha raciocínio privado. Devolva somente um objeto JSON que associe cada task_id à sua sequência de códigos. Use apenas códigos do respectivo caso e não inclua explicações."},
            {"role": "user", "content": f"Experiência procedural disponível:\n{procedure_block}\n\nCatálogo de ações compartilhado:\n{actions}\n\nCasos públicos:\n" + "\n".join(cases)},
        ]

    async def _score_batched(self, experienced: bool) -> tuple[float, dict[str, float], list[dict]]:
        corpus = [item for entries in self.origin_corpus.values() for item in entries] if experienced else []
        self.dataset.assert_isolated(corpus)
        answers, tasks = self.dataset.private_answers(), self.dataset.public_tasks()
        grouped: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            grouped[str(task["family"])].append(task)
        hits: dict[str, list[bool]] = defaultdict(list)
        traces: list[dict] = []
        for family, family_tasks in sorted(grouped.items()):
            selected = self.origin_corpus.get(family, []) if experienced else []
            parsed: dict[str, str] = {}
            batch_outputs: list[str] = []
            known_ids = {str(task["id"]) for task in family_tasks}
            for start in range(0, len(family_tasks), self.batch_size):
                chunk = family_tasks[start : start + self.batch_size]
                reply = await self.models.generate(self._batch_messages(chunk, selected), self.model_name, seed=self.seed, max_tokens=256, json_mode=True)
                batch_outputs.append(reply.content)
                try:
                    response_map = json.loads(reply.content)
                except json.JSONDecodeError:
                    response_map = {}
                if isinstance(response_map, dict):
                    for task_id, raw in response_map.items():
                        if str(task_id) in known_ids and isinstance(raw, str):
                            parsed[str(task_id)] = self._normalise_plan(raw)
            public_output = "\n--- batch ---\n".join(batch_outputs)
            for task in family_tasks:
                expected = str(answers[task["id"]]["expected_sequence"]).upper()
                actual = parsed.get(str(task["id"]), "")
                ok = actual == expected
                hits[family].append(ok)
                traces.append({"task_id": task["id"], "family": family, "expected": expected, "actual": actual, "success": ok, "mode": "experienced" if experienced else "fresh", "execution": "batched_by_family", "batch_output": public_output})
        family_scores = {name: round(sum(values) / len(values), 4) for name, values in hits.items()}
        return round(sum(sum(values) for values in hits.values()) / len(tasks), 4), family_scores, traces

    async def _score(self, experienced: bool) -> tuple[float, dict[str, float], list[dict]]:
        if self.batch_by_family:
            return await self._score_batched(experienced)
        corpus = [item for entries in self.origin_corpus.values() for item in entries] if experienced else []
        self.dataset.assert_isolated(corpus)
        answers, tasks = self.dataset.private_answers(), self.dataset.public_tasks()
        hits: dict[str, list[bool]] = defaultdict(list)
        traces: list[dict] = []
        for task in tasks:
            selected = self.origin_corpus.get(str(task["family"]), []) if experienced else []
            reply = await self.models.generate(self._messages(task, selected), self.model_name, seed=self.seed, max_tokens=16)
            actual = self._normalise_plan(reply.content)
            expected = str(answers[task["id"]]["expected_sequence"]).upper()
            ok = actual == expected
            hits[str(task["family"])].append(ok)
            traces.append({"task_id": task["id"], "family": task["family"], "expected": expected, "actual": actual, "success": ok, "mode": "experienced" if experienced else "fresh", "execution": "per_task"})
        family = {name: round(sum(values) / len(values), 4) for name, values in hits.items()}
        return round(sum(sum(values) for values in hits.values()) / len(tasks), 4), family, traces

    async def run_async(self) -> dict:
        fresh, fresh_by, fresh_traces = await self._score(False)
        experienced, experienced_by, experienced_traces = await self._score(True)
        gain_by = {name: round(experienced_by[name] - fresh_by[name], 4) for name in sorted(fresh_by)}
        run_id = str(uuid4())
        artifact = self.settings.artifacts_dir / "transfer" / self.benchmark_name / run_id
        artifact.mkdir(parents=True, exist_ok=True)
        version = "procedural-v2" if self.benchmark_name == "transfer20" else "transfer100-v3" if self.benchmark_name == "transfer100_v3" else "transfer100-v2"
        result = {"run_id": run_id, "benchmark_version": version, "benchmark": self.benchmark_name, "execution_mode": "batched_by_family" if self.batch_by_family else "per_task", "fresh": fresh, "experienced": experienced, "transfer_gain": round(experienced - fresh, 4), "by_family": gain_by, "seed": self.seed, "model": self.model_name, "traces": {"fresh": fresh_traces, "experienced": experienced_traces}}
        (artifact / "transfer.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.db.execute("INSERT INTO transfer_runs (id,family,model_name,seed,fresh_score,experienced_score,transfer_gain,artifact_dir,created_at) VALUES (?, 'aggregate', ?, ?, ?, ?, ?, ?, ?)", (run_id, self.model_name, self.seed, fresh, experienced, result["transfer_gain"], str(artifact), datetime.now(UTC).isoformat()))
        return result

    def run(self) -> dict:
        return asyncio.run(self.run_async())


class TransferRoutingAblation(TransferExperiment):
    """Ablação Hermes por tarefa, com Router consumindo somente utilidade prévia."""

    def __init__(self, *args: object, contract_root: Path, **kwargs: object):
        super().__init__(*args, benchmark_name="transfer100_v3", contract_root=contract_root, **kwargs)
        if self.batch_by_family:
            raise ValueError("A ablação Hermes requer execução per-task")
        self.routing = ShadowExperienceRoutingService(self.db)

    @staticmethod
    def _category(family: str) -> str:
        return "recovery" if family in {"dependency_recovery", "state_recovery"} else "reasoning"

    def _routing_result(self, task: dict):
        family = str(task["family"])
        signature = TaskSignatureClassifier.classify({**task, "category": self._category(family), "required_tools": ["benchmark.action"]})
        origin = ExperienceSignature(category=signature.category, family=family, domain=str(task["source_domain"]), tool_families=["benchmark.action"], abstraction_level=0.9, verified=True, source="transfer100_v3_origin")
        return self.routing.evaluate(signature, f"transfer100_v3_origin:{family}", origin, task_id=None)

    async def _score_condition(self, condition: InjectionCondition, baseline: dict[str, bool] | None = None) -> tuple[float, dict[str, float], list[dict], float]:
        answers, tasks = self.dataset.private_answers(), self.dataset.public_tasks()
        corpus = [item for entries in self.origin_corpus.values() for item in entries]
        self.dataset.assert_isolated(corpus)
        hits: dict[str, list[bool]] = defaultdict(list)
        traces: list[dict] = []
        harmful = injected = 0
        for task in tasks:
            family = str(task["family"])
            decision, reason = "NOT_EVALUATED", "condition_never"
            expected_utility = compatibility = None
            procedures: list[str] = []
            if condition == "always_inject":
                procedures, decision, reason = self.origin_corpus.get(family, []), "USE", "condition_always"
            elif condition == "router_use_abstain_reject":
                routed = self._routing_result(task)
                decision, reason = routed.decision.value, routed.reason
                expected_utility, compatibility = routed.expected_utility, routed.compatibility
                if decision == "USE":
                    procedures = self.origin_corpus.get(family, [])
            if procedures:
                injected += 1
            reply = await self.models.generate(self._messages(task, procedures), self.model_name, seed=self.seed, max_tokens=16)
            actual = self._normalise_plan(reply.content)
            expected = str(answers[task["id"]]["expected_sequence"]).upper()
            ok = actual == expected
            if procedures and baseline is not None and baseline.get(str(task["id"]), False) and not ok:
                harmful += 1
            hits[family].append(ok)
            traces.append({"task_id": task["id"], "family": family, "expected": expected, "actual": actual, "success": ok, "condition": condition, "execution": "per_task", "injected": bool(procedures), "routing_decision": decision, "routing_reason": reason, "expected_utility": expected_utility, "compatibility": compatibility})
        score = round(sum(sum(values) for values in hits.values()) / len(tasks), 4)
        return score, {name: round(sum(values) / len(values), 4) for name, values in hits.items()}, traces, round(harmful / injected, 4) if injected else 0.0

    async def run_async(self) -> dict:
        run_id = str(uuid4())
        scores: dict[str, float] = {}
        by_family: dict[str, dict[str, float]] = {}
        traces: dict[str, list[dict]] = {}
        harmful_rates: dict[str, float] = {}
        baseline: dict[str, bool] | None = None
        for condition in ROUTING_CONDITIONS:
            score, families, condition_traces, harmful_rate = await self._score_condition(condition, baseline)
            scores[condition], by_family[condition], traces[condition], harmful_rates[condition] = score, families, condition_traces, harmful_rate
            if condition == "never_inject":
                baseline = {str(item["task_id"]): bool(item["success"]) for item in condition_traces}
        artifact = self.settings.artifacts_dir / "research" / "hermes" / "transfer100_v3" / run_id
        artifact.mkdir(parents=True, exist_ok=True)
        result = {"run_id": run_id, "benchmark": "transfer100_v3", "benchmark_version": "transfer100-v3-routing-per-task", "execution_mode": "per_task", "seed": self.seed, "model": self.model_name, "conditions": scores, "transfer_gain_vs_never": {name: round(score - scores["never_inject"], 4) for name, score in scores.items() if name != "never_inject"}, "abstention_value": round(scores["router_use_abstain_reject"] - scores["always_inject"], 4), "harmful_retrieval_rate": harmful_rates, "by_family": by_family, "traces": traces}
        (artifact / "routing_ablation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
