"""Harness científico append-only para diagnosticar ganho cognitivo no UltronPro."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ultron.benchmarks.cgfe import CGFEExperiment
from ultron.benchmarks.runner import UGIBLiteRunner
from ultron.configuration import Settings
from ultron.db import Database
from ultron.memory.service import MemoryService
from ultron.research.learn2 import Learn2Experiment
from ultron.research.statistics import summarize
from ultron.schemas import MemorySearch


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    system: int = 0
    goal: int = 0
    plan: int = 0
    memory: int = 0
    skills: int = 0
    tools: int = 0
    observations: int = 0
    history: int = 0

    @property
    def total(self) -> int:
        return sum((self.system, self.goal, self.plan, self.memory, self.skills, self.tools, self.observations, self.history))

    def model_dump(self) -> dict[str, int]:
        return {"system": self.system, "goal": self.goal, "plan": self.plan, "memory": self.memory, "skills": self.skills, "tools": self.tools, "observations": self.observations, "history": self.history, "total": self.total}


class ContextBudgeter:
    """Seleciona blocos por orçamento; ativado experimentalmente, nunca como alteração invisível de produção."""

    def __init__(self, max_input_tokens: int, allocations: dict[str, float]):
        self.max_input_tokens, self.allocations = max_input_tokens, allocations

    def select(self, blocks: dict[str, str]) -> tuple[dict[str, str], ContextMetrics]:
        chosen: dict[str, str] = {}
        counts: dict[str, int] = {}
        for name, value in blocks.items():
            budget = int(self.max_input_tokens * float(self.allocations.get(name, 0.0)))
            text = str(value or "")
            chosen[name] = text[: budget * 4]
            counts[name] = max(0, len(chosen[name]) // 4)
        metrics = ContextMetrics(
            system=counts.get("system", 0), goal=counts.get("task", 0), plan=counts.get("plan", 0),
            memory=counts.get("memory", 0), skills=counts.get("skills", 0), tools=counts.get("tools", 0),
            observations=counts.get("observations", 0), history=counts.get("history", 0),
        )
        return chosen, metrics


class HypothesisLog:
    def __init__(self, root: Path):
        self.path = root / "data" / "research" / "hypotheses.jsonl"

    def append(self, statement: str, experiment: str, expected_result: str, status: str = "open", conclusion: str | None = None) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"id": str(uuid4()), "statement": statement, "experiment": experiment, "expected_result": expected_result, "status": status, "conclusion": conclusion, "created_at": utcnow()}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


class DiagnosticHarness:
    """Executa uma variável por vez e preserva todos os resultados, inclusive negativos."""

    MEMORY_CORPUS = {
        "episodic": ["Em tarefas anteriores, verifiquei a condição de sucesso antes de declarar conclusão."],
        "semantic": ["Resultados estruturados exigem somente os campos solicitados e validação de formato."],
        "procedural": ["Selecione ferramenta permitida, opere em workspace isolado e confirme o artefato final."],
        "self": ["Quando a evidência é insuficiente, registre a lacuna em vez de inventar um resultado."],
        "world": ["Caminhos e comandos externos devem ser tratados como não confiáveis até validação pela política."],
        "skills": ["Skill validada: classificar falha, limitar tentativas e aplicar recuperação segura."],
    }

    def __init__(self, settings: Settings, model_name: str | None = None, seed: int = 42):
        self.settings, self.model_name, self.seed = settings, model_name, seed
        self.db = Database(settings.db_path)
        self.db.initialize()
        self.hypotheses = HypothesisLog(settings.root_dir)

    def _config_hash(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _artifact_dir(self, family: str) -> Path:
        folder = self.settings.artifacts_dir / "research" / family / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=False)
        return folder

    def _persist(self, experiment: str, hypothesis_id: str, folder: Path, payload: dict[str, Any]) -> None:
        manifest = {"run_id": str(uuid4()), "experiment": experiment, "model": self.model_name or self.settings.raw["models"]["primary"], "seed": self.seed, "config_hash": self._config_hash(payload.get("configuration", {})), "created_at": utcnow(), "negative_result_policy": "never_discard_bad_run"}
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.db.execute(
            "INSERT INTO diagnostic_runs (id,experiment,hypothesis_id,model_name,seed,config_hash,manifest_json,result_json,artifact_dir,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (manifest["run_id"], experiment, hypothesis_id, manifest["model"], self.seed, manifest["config_hash"], self.db.json(manifest), self.db.json(payload), str(folder), manifest["created_at"]),
        )

    async def memory_topk(self, values: list[int] | None = None) -> dict[str, Any]:
        values = values or [0, 1, 2, 3, 5, 8, 10]
        hypothesis = self.hypotheses.append("Excessive memory Top-K reduces performance.", "MEM-1", "Existe um top-k com score ou eficiência superior.")
        contexts = [f"Princípio procedural {index}: valide entrada, restrições e evidência antes de concluir." for index in range(1, 11)]
        rows: list[dict[str, Any]] = []
        for top_k in values:
            runner = UGIBLiteRunner(self.settings)
            mode = "ultron-fresh" if top_k == 0 else "ultron-experienced"
            manifest, summary = await runner.run_async(mode, self.model_name, self.seed, experience_context=contexts[:top_k], experience_limit=top_k)
            folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            folder.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, folder)
            injected = sum(len(item) // 4 for item in contexts[:top_k])
            rows.append({"top_k": top_k, "run_id": manifest.run_id, "score": summary.score, "cgfe": 0.0, "tokens_injected": injected, "context_efficiency": round(summary.score / max(injected, 1), 6), "average_steps": summary.average_steps, "average_latency_ms": summary.average_latency_ms})
        baseline = next(item["score"] for item in rows if item["top_k"] == 0)
        for row in rows:
            row["cgfe"] = round(row["score"] - baseline, 6)
        best = max(rows, key=lambda item: (item["score"], -item["tokens_injected"]))
        result = {"configuration": {"top_k_values": values}, "baseline_score": baseline, "best_top_k": best["top_k"], "results": rows}
        folder = self._artifact_dir("memory_topk")
        self._persist("MEM-1", hypothesis["id"], folder, result)
        return result

    def retrieval_quality(self, top_k: int = 3) -> dict[str, Any]:
        """MEM-3: mede Precision@K em um conjunto rotulado, sem usar o benchmark UGIB."""
        source = self.settings.root_dir / "benchmarks" / "memory_eval" / "mem_eval_v0.yaml"
        dataset = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        eval_db = Database(self.settings.data_dir / "memory_eval.db")
        eval_db.initialize()
        memory = MemoryService(eval_db)
        for item in dataset.get("memories", []):
            eval_db.execute(
                "INSERT OR IGNORE INTO memories (id,type,content,summary,importance,confidence,source,created_at,access_count,usefulness) VALUES (?, ?, ?, ?, 0.8, 1.0, 'memory_eval', ?, 0, 0.5)",
                (item["id"], item["type"], item["content"], item["content"][:120], utcnow()),
            )
            eval_db.execute("INSERT OR IGNORE INTO memories_fts (memory_id,content,summary) VALUES (?, ?, ?)", (item["id"], item["content"], item["content"][:120]))
        rows = []
        for query in dataset.get("queries", []):
            selected = memory.search(MemorySearch(query=query["query"], limit=top_k), top_k=top_k)
            ids = [item["id"] for item in selected]
            relevant = set(query.get("relevant_memory_ids", [])) | set(query.get("acceptable_memory_ids", []))
            harmful = set(query.get("harmful_memory_ids", []))
            rows.append({"query": query["query"], "selected": ids, "precision_at_k": round(sum(item in relevant for item in ids) / max(len(ids), 1), 6), "harmful_selected": sorted(set(ids) & harmful)})
        precision = summarize(item["precision_at_k"] for item in rows)
        harmful = sorted({memory_id for item in rows for memory_id in item["harmful_selected"]})
        hypothesis = self.hypotheses.append("Retrieval relevance e utilidade empírica são mensuráveis separadamente.", "MEM-3", "Precision@K expõe candidatos relevantes e memórias prejudiciais.")
        payload = {"configuration": {"top_k": top_k, "dataset_version": dataset.get("version")}, "queries": rows, "precision_at_k": precision.model_dump(), "harmful_memories": harmful}
        folder = self._artifact_dir("retrieval")
        self._persist("MEM-3", hypothesis["id"], folder, payload)
        return payload

    async def memory_types(self) -> dict[str, Any]:
        variants = {"NONE": [], "EPISODIC": ["episodic"], "SEMANTIC": ["semantic"], "PROCEDURAL": ["procedural"], "SELF": ["self"], "WORLD": ["world"], "SKILLS_ONLY": ["skills"], "SEMANTIC_PROCEDURAL": ["semantic", "procedural"], "PROCEDURAL_SKILLS": ["procedural", "skills"], "ALL": list(self.MEMORY_CORPUS)}
        hypothesis = self.hypotheses.append("Procedural memory is more useful than episodic memory.", "MEM-2", "Uma configuração de tipo supera NONE.")
        rows: list[dict[str, Any]] = []
        for name, kinds in variants.items():
            context = [entry for kind in kinds for entry in self.MEMORY_CORPUS[kind]]
            runner = UGIBLiteRunner(self.settings)
            mode = "ultron-fresh" if not context else "ultron-experienced"
            manifest, summary = await runner.run_async(mode, self.model_name, self.seed, experience_context=context)
            folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            folder.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, folder)
            rows.append({"memory_type": name, "run_id": manifest.run_id, "score": summary.score, "context_tokens": sum(len(item) // 4 for item in context), "retrieval_count": len(context)})
        baseline = next(item["score"] for item in rows if item["memory_type"] == "NONE")
        for row in rows:
            row["delta"] = round(row["score"] - baseline, 6)
        result = {"configuration": {"variants": list(variants)}, "baseline_score": baseline, "results": rows}
        folder = self._artifact_dir("memory_ablation")
        self._persist("MEM-2", hypothesis["id"], folder, result)
        return result

    async def context_ablation(self) -> dict[str, Any]:
        """CTX-1/CTX-2: mede blocos de contexto sem mudar modelo, seed ou benchmark."""
        hypothesis = self.hypotheses.append("Full context causes overload on small models.", "CTX-1/CTX-2", "MINIMAL ou uma ablação supera FULL em modelos pequenos.")
        full = {"memory": "Memória: validar evidência, formato e recuperação segura.", "skills": "Skill: use ferramenta permitida e verifique resultado.", "plan": "Plano: analisar, executar, verificar e aprender.", "history": "Histórico: execução anterior foi registrada com sucesso.", "observations": "Observação: nenhuma falha ativa."}
        variants = {"FULL": full, "NO_MEMORY": {key: value for key, value in full.items() if key != "memory"}, "NO_SKILLS": {key: value for key, value in full.items() if key != "skills"}, "NO_LONG_HISTORY": {key: value for key, value in full.items() if key != "history"}, "NO_PLAN_HISTORY": {key: value for key, value in full.items() if key not in {"plan", "history"}}, "MINIMAL": {"observations": full["observations"]}}
        rows = []
        for name, blocks in variants.items():
            runner = UGIBLiteRunner(self.settings)
            manifest, summary = await runner.run_async("ultron-fresh", self.model_name, self.seed, extra_context=blocks)
            folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            folder.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, folder)
            totals = [item.execution.context_metrics.get("total", 0) for item in summary.results]
            rows.append({"variant": name, "run_id": manifest.run_id, "score": summary.score, "average_context_tokens": round(sum(totals) / max(len(totals), 1), 4), "average_steps": summary.average_steps, "average_latency_ms": summary.average_latency_ms})
        baseline = next(item["score"] for item in rows if item["variant"] == "FULL")
        for row in rows:
            row["delta_vs_full"] = round(row["score"] - baseline, 6)
        payload = {"configuration": {"variants": list(variants)}, "results": rows, "interpretation": "Correlação e deltas são descritivos; não estabelecem causalidade isoladamente."}
        folder = self._artifact_dir("context")
        self._persist("CTX-1/CTX-2", hypothesis["id"], folder, payload)
        return payload

    async def model_matrix(self, models: list[str] | None = None) -> dict[str, Any]:
        """MODEL-1: matriz de modelos e variantes, sem baixar runtimes ou modelos."""
        hypothesis = self.hypotheses.append("O modelo smoke pode estar abaixo do limiar de capacidade para a arquitetura completa.", "MODEL-1", "Ao menos um modelo supera LLM+tools sob o mesmo protocolo.")
        configured = self.settings.raw["models"]
        models = models or list(dict.fromkeys(item for item in [configured.get("smoke"), configured.get("research_small"), configured.get("research_primary")] if item))
        variants = {"A_LLM_ONLY": "baseline", "B_LLM_TOOLS": "tools", "C_ORCHESTRATOR": "ultron-fresh", "E_MEMORY": "ultron-experienced", "F_MEMORY_SKILLS": "ultron-experienced"}
        rows = []
        for model in models:
            for label, mode in variants.items():
                context = self.MEMORY_CORPUS["procedural"] if label in {"E_MEMORY", "F_MEMORY_SKILLS"} else []
                if label == "F_MEMORY_SKILLS":
                    context += self.MEMORY_CORPUS["skills"]
                runner = UGIBLiteRunner(self.settings)
                manifest, summary = await runner.run_async(mode, model, self.seed, experience_context=context)
                folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
                folder.mkdir(parents=True, exist_ok=True)
                runner.persist_run(manifest, summary, folder)
                invalid = sum(item.execution.failure_category is not None for item in summary.results)
                rows.append({"model": model, "variant": label, "mode": mode, "run_id": manifest.run_id, "score": summary.score, "latency_ms": summary.average_latency_ms, "invalid_outputs": invalid, "ram_mb": None, "vram_mb": None})
        payload = {"configuration": {"models": models, "variants": list(variants)}, "results": rows}
        folder = self._artifact_dir("models")
        self._persist("MODEL-1", hypothesis["id"], folder, payload)
        return payload

    async def orchestrator_cost(self) -> dict[str, Any]:
        """ORCH-1: compara complexidade incremental com tools direct na mesma seed."""
        hypothesis = self.hypotheses.append("A menor arquitetura que supera tools direct é preferível.", "ORCH-1", "Uma configuração de orquestração supera tools direct.")
        variants = {"TOOLS_DIRECT": ("tools", [], {}), "ORCH_MINIMAL": ("ultron-fresh", [], {"observations": "Verifique a saída final."}), "ORCH_STANDARD": ("ultron-fresh", [], {"plan": "Planeje, execute, recupere e verifique."}), "ORCH_FULL": ("ultron-experienced", self.MEMORY_CORPUS["procedural"] + self.MEMORY_CORPUS["skills"], {"plan": "Planeje, execute, recupere e verifique."})}
        rows = []
        for name, (mode, context, blocks) in variants.items():
            runner = UGIBLiteRunner(self.settings)
            manifest, summary = await runner.run_async(mode, self.model_name, self.seed, experience_context=context, extra_context=blocks)
            folder = self.settings.artifacts_dir / "benchmarks" / manifest.run_id
            folder.mkdir(parents=True, exist_ok=True)
            runner.persist_run(manifest, summary, folder)
            rows.append({"variant": name, "run_id": manifest.run_id, "score": summary.score, "average_steps": summary.average_steps, "average_latency_ms": summary.average_latency_ms})
        baseline = next(item["score"] for item in rows if item["variant"] == "TOOLS_DIRECT")
        for row in rows:
            row["orchestrator_delta"] = round(row["score"] - baseline, 6)
        payload = {"configuration": {"variants": list(variants)}, "results": rows}
        folder = self._artifact_dir("orchestrator")
        self._persist("ORCH-1", hypothesis["id"], folder, payload)
        return payload

    async def multi_seed_cgfe(self, seeds: list[int] | None = None, experience_count: int = 50) -> dict[str, Any]:
        seeds = seeds or list(range(42, 52))
        hypothesis = self.hypotheses.append("A configuração experiente supera fresh em múltiplas seeds.", "SEED-1", "mean(CGFE) > 0 sem selecionar a melhor seed.")
        rows = []
        for seed in seeds:
            result = await CGFEExperiment(self.settings, self.model_name, seed).run_async(experience_count)
            rows.append({"seed": seed, **result.as_dict()})
        summary = {"fresh": summarize(item["fresh_score"] for item in rows).model_dump(), "experienced": summarize(item["experienced_score"] for item in rows).model_dump(), "cgfe": summarize(item["cgfe"] for item in rows).model_dump()}
        payload = {"configuration": {"seeds": seeds, "experience_count": experience_count}, "results": rows, "statistics": summary}
        folder = self._artifact_dir("seeds")
        self._persist("SEED-1", hypothesis["id"], folder, payload)
        return payload

    async def experience_scaling(self, counts: list[int] | None = None) -> dict[str, Any]:
        counts = counts or [10, 25, 50, 100, 200]
        hypothesis = self.hypotheses.append("Mais experiência útil melhora CGFE até saturar ou degradar.", "LEARN-1", "A curva CGFE(N) identifica ganho, plateau ou poluição.")
        rows = []
        for count in counts:
            result = await CGFEExperiment(self.settings, self.model_name, self.seed).run_async(count)
            rows.append({"experience_count": count, **result.as_dict()})
        payload = {"configuration": {"counts": counts}, "results": rows}
        folder = self._artifact_dir("experience_scaling")
        self._persist("LEARN-1", hypothesis["id"], folder, payload)
        return payload

    async def learn2(self, counts: list[int] | None = None) -> dict[str, Any]:
        """LEARN-2: mede CGFE(N) apenas com experiências verificadas e admitidas."""
        counts = counts or [0, 10, 25, 50, 100, 200]
        hypothesis = self.hypotheses.append(
            "Experiências verificadas, filtradas por MAS e category-compatible melhoram CGFE até saturar ou degradar.",
            "LEARN-2",
            "A curva CGFE(N) permite identificar ganho, plateau ou regressão sem usar experiências triviais.",
        )
        experiment = Learn2Experiment(self.settings, self.model_name, self.seed)
        rows = await experiment.run_curve_async(counts)
        payload = {
            "configuration": {
                "counts": counts,
                "selection_policy": "MAS_verified_category_compatible",
                "negative_result_policy": "never_discard_bad_run",
            },
            "results": rows,
            "admitted_pool_size": experiment.pool.admitted_count,
        }
        folder = self._artifact_dir("learn2")
        self._persist("LEARN-2", hypothesis["id"], folder, payload)
        return payload

    def run(self, coroutine: Any) -> dict[str, Any]:
        return asyncio.run(coroutine)
