"""Harness Transfer-20 para transferência procedural sem vazamento de tarefas-alvo.

O benchmark mantém tarefas e contratos separados. A condição ``experienced`` recebe
apenas procedimentos abstratos aprendidos no domínio de origem; o verificador
compara, de modo determinístico, a sequência de códigos produzida com o contrato
privado do domínio-alvo.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from ultron.configuration import Settings
from ultron.db import Database
from ultron.models.gateway import ModelGateway


class TransferDataset:
    """Carrega a parte pública e os contratos privados do Transfer-20."""

    def __init__(self, root: Path):
        self.root = root

    def public_tasks(self) -> list[dict]:
        tasks = yaml.safe_load((self.root / "tasks.yaml").read_text(encoding="utf-8")) or []
        if not isinstance(tasks, list):
            raise ValueError("tasks.yaml do Transfer-20 deve conter uma lista")
        return tasks

    def private_answers(self) -> dict[str, dict]:
        answers = json.loads((self.root / "answers.json").read_text(encoding="utf-8"))
        if not isinstance(answers, dict):
            raise ValueError("answers.json do Transfer-20 deve conter um objeto")
        return answers

    def assert_isolated(self, experience_corpus: list[str]) -> None:
        """Rejeita corpus que contenha texto público ou contrato privado do alvo."""
        public = "\n".join(
            "\n".join(str(value) for value in task.values()) for task in self.public_tasks()
        ).casefold()
        private = (self.root / "answers.json").read_text(encoding="utf-8").casefold()
        for item in experience_corpus:
            candidate = item.strip().casefold()
            if candidate and (candidate in public or candidate in private):
                raise RuntimeError("Data leakage detectado no corpus de transferência")

    def families(self) -> set[str]:
        return {str(task["family"]) for task in self.public_tasks()}


class TransferExperiment:
    """Compara execução fresh e experienced com o mesmo modelo e seed.

    Os procedimentos abaixo descrevem invariantes de decisão, não comandos,
    respostas, códigos de ação, fixtures ou nomes de artefatos do domínio-alvo.
    """

    ORIGIN_CORPUS = {
        "structured_validation": [
            "Para validar dados estruturados, primeiro confirme que a entrada pode ser lida, depois valide campos obrigatórios e tipos, e só então aceite o resultado."
        ],
        "dependency_recovery": [
            "Para recuperar uma dependência, primeiro identifique a declaração de estado, depois restaure somente o recurso declarado e por fim execute uma verificação de resolução."
        ],
        "recovery": [
            "Para recuperar estado, primeiro inspecione a situação atual, preserve o escopo da alteração, aplique apenas a reversão autorizada e confirme o estado final."
        ],
        "planning": [
            "Para planejar etapas dependentes, ordene as pré-condições antes dos dependentes, bloqueie a execução sem evidência da pré-condição e valide a conclusão de cada etapa."
        ],
        "configuration_repair": [
            "Para reparar configuração, inspecione estrutura e valores, aplique somente a mudança autorizada e valide o resultado antes de concluir."
        ],
    }

    def __init__(self, settings: Settings, model_name: str = "ollama_research", seed: int = 42, benchmark_name: str = "transfer20", origin_corpus: dict[str, list[str]] | None = None, batch_by_family: bool = False, batch_size: int = 5):
        self.settings, self.model_name, self.seed = settings, model_name, seed
        self.benchmark_name = benchmark_name
        self.origin_corpus = origin_corpus or self.ORIGIN_CORPUS
        self.batch_by_family = batch_by_family
        self.batch_size = max(1, batch_size)
        self.dataset = TransferDataset(settings.root_dir / "benchmarks" / benchmark_name)
        self.db, self.models = Database(settings.db_path), ModelGateway(settings)
        self.db.initialize()

    @staticmethod
    def _normalise_plan(reply: str) -> str:
        """Extrai uma sequência de códigos de ação sem delegar julgamento ao LLM."""
        clean = reply.upper().replace("→", ">")
        tokens = re.findall(r"\b[A-Z]{1,3}\d?\b", clean)
        return ">".join(tokens)

    def _messages(self, task: dict, procedures: list[str]) -> list[dict[str, str]]:
        procedure_block = "\n".join(f"- {item}" for item in procedures) or "- Nenhuma experiência prévia disponível."
        action_lines = "\n".join(
            f"{action['code']}: {action['description']}" for action in task["actions"]
        )
        return [
            {
                "role": "system",
                "content": (
                    "Você é um executor local de benchmark. Não use internet e não exponha raciocínio privado. "
                    "Escolha apenas códigos que aparecem no caso e entregue somente a sequência pedida."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Experiência procedural disponível:\n{procedure_block}\n\n"
                    f"Caso alvo ({task['target_domain']}):\n{task['objective']}\n\n"
                    f"Ações disponíveis:\n{action_lines}\n\n"
                    f"Formato obrigatório: {task['response_format']}"
                ),
            },
        ]

    def _batch_messages(self, tasks: list[dict], procedures: list[str]) -> list[dict[str, str]]:
        procedure_block = "\n".join(f"- {item}" for item in procedures) or "- Nenhuma experiência prévia disponível."
        actions = "; ".join(f"{item['code']}: {item['description']}" for item in tasks[0]["actions"])
        cases = [f"{task['id']} | {task['objective']}" for task in tasks]
        return [
            {
                "role": "system",
                "content": "Executor local de benchmark. Não use internet nem exponha raciocínio privado. Devolva somente um objeto JSON que associe cada task_id à sua sequência de códigos. Exemplo: {\"configuration_repair_01\": \"I>R>V\"}. Use apenas códigos do respectivo caso e não inclua explicações.",
            },
            {
                "role": "user",
                "content": f"Experiência procedural disponível:\n{procedure_block}\n\nCatálogo de ações compartilhado:\n{actions}\n\nCasos públicos:\n" + "\n".join(cases),
            },
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
                reply = await self.models.generate(
                    self._batch_messages(chunk, selected),
                    self.model_name,
                    seed=self.seed,
                                        max_tokens=256,
                    json_mode=True,
                )
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
                traces.append(
                    {
                        "task_id": task["id"],
                        "family": family,
                        "expected": expected,
                        "actual": actual,
                        "success": ok,
                        "mode": "experienced" if experienced else "fresh",
                        "execution": "batched_by_family",
                        "batch_output": public_output,
                    }
                )
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
            reply = await self.models.generate(
                self._messages(task, selected), self.model_name, seed=self.seed, max_tokens=16
            )
            actual = self._normalise_plan(reply.content)
            expected = str(answers[task["id"]]["expected_sequence"]).upper()
            ok = actual == expected
            hits[str(task["family"])].append(ok)
            traces.append(
                {
                    "task_id": task["id"],
                    "family": task["family"],
                    "expected": expected,
                    "actual": actual,
                    "success": ok,
                    "mode": "experienced" if experienced else "fresh",
                }
            )
        family = {name: round(sum(values) / len(values), 4) for name, values in hits.items()}
        return round(sum(sum(values) for values in hits.values()) / len(tasks), 4), family, traces

    async def run_async(self) -> dict:
        fresh, fresh_by, fresh_traces = await self._score(False)
        experienced, experienced_by, experienced_traces = await self._score(True)
        gain_by = {
            name: round(experienced_by[name] - fresh_by[name], 4)
            for name in sorted(fresh_by)
        }
        run_id = str(uuid4())
        artifact = self.settings.artifacts_dir / "transfer" / self.benchmark_name / run_id
        artifact.mkdir(parents=True, exist_ok=True)
        result = {
            "run_id": run_id,
            "benchmark_version": "procedural-v2" if self.benchmark_name == "transfer20" else "transfer100-v2-batched" if self.batch_by_family else "transfer100-v1",
            "benchmark": self.benchmark_name,
            "execution_mode": "batched_by_family" if self.batch_by_family else "per_task",
            "fresh": fresh,
            "experienced": experienced,
            "transfer_gain": round(experienced - fresh, 4),
            "by_family": gain_by,
            "seed": self.seed,
            "model": self.model_name,
            "traces": {"fresh": fresh_traces, "experienced": experienced_traces},
        }
        (artifact / "transfer.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.db.execute(
            "INSERT INTO transfer_runs (id,family,model_name,seed,fresh_score,experienced_score,transfer_gain,artifact_dir,created_at) VALUES (?, 'aggregate', ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                self.model_name,
                self.seed,
                fresh,
                experienced,
                result["transfer_gain"],
                str(artifact),
                datetime.now(UTC).isoformat(),
            ),
        )
        return result

    def run(self) -> dict:
        return asyncio.run(self.run_async())
