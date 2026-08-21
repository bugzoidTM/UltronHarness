"""Memória persistente com retrieval híbrido, vetores locais e consolidação controlada."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from ultron.configuration import Settings
from ultron.db import Database
from ultron.memory.embeddings import (
    HashEmbeddingProvider,
    OllamaEmbeddingProvider,
    PersistentVectorStore,
)
from ultron.schemas import MemoryCreate, MemorySearch


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class MemoryService:
    def __init__(self, db: Database, settings: Settings | None = None):
        self.db = db
        self.settings = settings
        memory_config = settings.raw["memory"] if settings else {}
        self.weights = memory_config.get(
            "retrieval_weights",
            {"semantic": 0.50, "lexical": 0.20, "relevance": 0.0, "recency": 0.10, "importance": 0.10, "usefulness": 0.10},
        )
        self.top_k = int(memory_config.get("retrieval", {}).get("top_k", 3))
        self.feature_flags = memory_config.get("feature_flags", {})
        self.vectors: PersistentVectorStore | None = None
        self.embeddings = HashEmbeddingProvider()
        if settings and memory_config.get("vector_enabled", False):
            embedding_config = memory_config.get("embeddings", {})
            try:
                if embedding_config.get("provider") == "ollama":
                    self.embeddings = OllamaEmbeddingProvider(
                        embedding_config.get("endpoint", "http://127.0.0.1:11434"),
                        embedding_config["model"],
                        int(embedding_config.get("timeout_seconds", 30)),
                    )
                    probe = self.embeddings.embed_text("ultronpro embedding health check")
                    self.vectors = PersistentVectorStore(settings.data_dir / "vectors", len(probe))
                else:
                    self.vectors = PersistentVectorStore(settings.data_dir / "vectors", 128)
            except Exception:
                # Degrada graciosamente para FTS/hash sem impedir o plano de controle local.
                self.embeddings = HashEmbeddingProvider()
                self.vectors = PersistentVectorStore(settings.data_dir / "vectors", 128)

    def create(self, payload: MemoryCreate) -> dict:
        memory_id, created_at = str(uuid4()), utcnow()
        self.db.execute(
            """INSERT INTO memories (id,type,content,summary,importance,confidence,source,provenance,task_id,created_at,last_accessed,access_count,usefulness,valid_from,valid_until)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0.5, ?, ?)""",
            (
                memory_id, payload.type, payload.content, payload.summary, payload.importance,
                payload.confidence, payload.source, payload.provenance, payload.task_id, created_at,
                payload.valid_from.isoformat() if payload.valid_from else None,
                payload.valid_until.isoformat() if payload.valid_until else None,
            ),
        )
        self.db.execute("INSERT INTO memories_fts (memory_id, content, summary) VALUES (?, ?, ?)", (memory_id, payload.content, payload.summary))
        if self.vectors:
            self.vectors.upsert(memory_id, self.embeddings.embed_text(f"{payload.summary}\n{payload.content}"))
        return self.get(memory_id) or {}

    def get(self, memory_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return self._normalize(row) if row else None

    def list(self, limit: int = 100, memory_type: str | None = None) -> list[dict]:
        if memory_type:
            rows = self.db.all("SELECT * FROM memories WHERE type = ? ORDER BY created_at DESC LIMIT ?", (memory_type, limit))
        else:
            rows = self.db.all("SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._normalize(row) for row in rows]

    def search(self, request: MemorySearch, top_k: int | None = None) -> list[dict]:
        """Recupera memória sob flags experimentais e persiste o ranking auditável."""
        tokens = [token for token in request.query.lower().split() if len(token) > 1]
        limit = max(0, top_k if top_k is not None else min(request.limit, self.top_k))
        rows = self.db.all("SELECT * FROM memories ORDER BY created_at DESC LIMIT 500")
        semantic_scores: dict[str, float] = {}
        if self.vectors:
            try:
                semantic_scores = self.vectors.search(self.embeddings.embed_text(request.query), max(limit * 8, 50))
            except Exception:
                semantic_scores = {}
        now = datetime.now(UTC)
        scored: list[tuple[float, dict]] = []
        for row in rows:
            if request.types and row["type"] not in request.types:
                continue
            if not bool(self.feature_flags.get(row["type"], True)):
                continue
            if request.task_id and row["task_id"] not in {None, request.task_id}:
                continue
            content = f"{row['content']} {row['summary']}".lower()
            lexical = sum(token in content for token in tokens) / max(len(tokens), 1)
            semantic = semantic_scores.get(row["id"], 0.0)
            importance, usefulness = float(row["importance"]), float(row["usefulness"])
            try:
                age_days = max((now - datetime.fromisoformat(row["created_at"])).total_seconds() / 86400, 0)
            except ValueError:
                age_days = 365
            recency = math.exp(-age_days / 90)
            relevance = 1.0 if request.task_id and row["task_id"] == request.task_id else 0.0
            score = (
                float(self.weights.get("semantic", 0.50)) * semantic
                + float(self.weights.get("lexical", 0.20)) * lexical
                + float(self.weights.get("relevance", 0.0)) * relevance
                + float(self.weights.get("recency", 0.10)) * recency
                + float(self.weights.get("importance", 0.10)) * importance
                + float(self.weights.get("usefulness", 0.10)) * usefulness
            )
            if score > 0:
                item = self._normalize(row)
                item.update({"score": round(score, 4), "semantic_score": round(semantic, 4), "lexical_score": round(lexical, 4), "recency_score": round(recency, 4), "importance_score": round(importance, 4), "usefulness_score": round(usefulness, 4)})
                scored.append((score, item))
        ranked = [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)]
        selected = ranked[:limit]
        timestamp, retrieval_id = utcnow(), str(uuid4())
        for item in selected:
            self.db.execute("UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE id=?", (timestamp, item["id"]))
        candidates = [{"memory_id": item["id"], "memory_type": item["type"], "semantic_score": item["semantic_score"], "lexical_score": item["lexical_score"], "recency_score": item["recency_score"], "importance_score": item["importance_score"], "usefulness_score": item["usefulness_score"], "final_score": item["score"]} for item in ranked]
        self.db.execute(
            "INSERT INTO memory_retrievals (id,task_id,query,memory_ids_json,scores_json,selected,used_by_agent,result_success,created_at) VALUES (?, ?, ?, ?, ?, 1, 0, NULL, ?)",
            (retrieval_id, request.task_id, request.query, self.db.json([item["id"] for item in selected]), self.db.json(candidates), timestamp),
        )
        self.db.execute(
            "INSERT INTO retrieval_traces (id,retrieval_id,task_id,query,candidates_json,selected_json,prompt_positions_json,prompt_included_json,result_success,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (str(uuid4()), retrieval_id, request.task_id, request.query, self.db.json(candidates), self.db.json([item["id"] for item in selected]), self.db.json(list(range(len(selected)))), self.db.json([item["id"] for item in selected]), timestamp),
        )
        return selected

    def update_usefulness(self, memory_ids: list[str], result_success: bool) -> None:
        """Compatibilidade operacional: atualiza o prior sem confundir isso com causalidade."""
        delta = 0.05 if result_success else -0.05
        for memory_id in memory_ids:
            self.db.execute("UPDATE memories SET usefulness=MIN(1.0, MAX(0.0, usefulness + ?)) WHERE id=?", (delta, memory_id))

    def record_empirical_utility(self, memory_ids: list[str], with_score: float, without_score: float, run_id: str | None = None, task_id: str | None = None) -> None:
        """Registra deltas observados; não atualiza utilidade após uma ocorrência isolada."""
        delta = round(float(with_score) - float(without_score), 6)
        outcome = "HELPFUL" if delta > 0 else "HARMFUL" if delta < 0 else "NEUTRAL"
        for memory_id in memory_ids:
            self.db.execute(
                "INSERT INTO memory_utility_observations (id,memory_id,run_id,task_id,with_memory_score,without_memory_score,delta,outcome,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid4()), memory_id, run_id, task_id, with_score, without_score, delta, outcome, utcnow()),
            )

    def empirical_utility(self, memory_id: str) -> dict:
        row = self.db.one(
            "SELECT COUNT(*) AS uses, SUM(CASE WHEN delta>0 THEN 1 ELSE 0 END) AS successful_uses, SUM(CASE WHEN delta<0 THEN 1 ELSE 0 END) AS failed_uses, AVG(delta) AS mean_delta FROM memory_utility_observations WHERE memory_id=?",
            (memory_id,),
        ) or {}
        uses = int(row.get("uses") or 0)
        mean_delta = float(row.get("mean_delta") or 0.0)
        classification = "UNKNOWN" if uses < 2 else "HELPFUL" if mean_delta > 0 else "HARMFUL" if mean_delta < 0 else "NEUTRAL"
        return {"memory_id": memory_id, "uses": uses, "successful_uses": int(row.get("successful_uses") or 0), "failed_uses": int(row.get("failed_uses") or 0), "mean_delta": round(mean_delta, 6), "classification": classification}

    def store_experience(self, task_id: str, strategy: str, actions: list[dict], result: str, success: bool, errors: list[str], lessons: list[str], quality: float) -> str:
        experience_id = str(uuid4())
        self.db.execute(
            "INSERT INTO experiences (id,task_id,strategy,actions_json,result,success,errors_json,lessons_json,quality,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (experience_id, task_id, strategy, self.db.json(actions), result, int(success), self.db.json(errors), self.db.json(lessons), quality, utcnow()),
        )
        narrative = f"Tarefa {task_id}: {result}. Lições: {'; '.join(lessons) or 'nenhuma lição explícita'}"
        self.create(MemoryCreate(type="episodic", content=narrative, summary=result[:400], importance=0.7 if success else 0.6, confidence=0.9, source="experience", task_id=task_id))
        for lesson in lessons:
            self.create(MemoryCreate(type="semantic", content=lesson, summary=lesson[:300], importance=0.65, confidence=0.7, source="reflection", task_id=task_id))
        return experience_id

    def consolidate(self) -> dict:
        episodes = self.db.all("SELECT * FROM memories WHERE type='episodic' ORDER BY created_at DESC LIMIT 200")
        created, seen = 0, set()
        for episode in episodes:
            summary = (episode["summary"] or episode["content"][:300]).strip()
            fingerprint = summary.lower()
            if not summary or fingerprint in seen:
                continue
            seen.add(fingerprint)
            existing = self.db.one("SELECT id FROM memories WHERE type='procedural' AND summary=?", (summary,))
            if not existing and ("sucesso" in episode["content"].lower() or "liç" in episode["content"].lower()):
                self.create(MemoryCreate(type="procedural", content=f"Procedimento consolidado a partir de experiência: {episode['content']}", summary=summary, importance=0.6, confidence=0.6, source="consolidation", task_id=episode["task_id"]))
                created += 1
        return {"episodes_examined": len(episodes), "procedural_memories_created": created}

    def _normalize(self, row: dict) -> dict:
        return {**row, "valid_from": row.get("valid_from"), "valid_until": row.get("valid_until")}
