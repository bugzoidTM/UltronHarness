"""Embeddings locais e índice Qdrant persistente, desacoplados do serviço de memória."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import httpx
from qdrant_client import QdrantClient, models


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddingProvider:
    """Provider de embeddings via endpoint local do Ollama, sem chamadas externas."""

    def __init__(self, endpoint: str, model: str, timeout_seconds: int = 30):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.endpoint}/api/embed", json={"model": self.model, "input": texts})
            response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(texts):
            raise ValueError("Ollama retornou quantidade inesperada de embeddings.")
        return [[float(value) for value in embedding] for embedding in embeddings]


class HashEmbeddingProvider:
    """Fallback offline estável: útil apenas para testes quando nenhum modelo de embedding foi instalado."""

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.casefold().split():
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            vector[index] += 1.0
        norm = sum(value * value for value in vector) ** 0.5
        return [value / norm for value in vector] if norm else vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class PersistentVectorStore:
    """Coleção local Qdrant com pontos associados ao id de memória canônico do SQLite."""

    collection_name = "memories"

    def __init__(self, path: Path, dimensions: int):
        path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(path))
        self.dimensions = dimensions
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
            )

    def upsert(self, memory_id: str, vector: list[float]) -> None:
        self.client.upsert(
            collection_name=self.collection_name,
            points=[models.PointStruct(id=memory_id, vector=vector, payload={"memory_id": memory_id})],
        )

    def search(self, vector: list[float], limit: int) -> dict[str, float]:
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            with_payload=False,
        )
        return {str(point.id): float(point.score) for point in result.points}
