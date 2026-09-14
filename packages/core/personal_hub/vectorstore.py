"""VectorStore: абстракция векторного индекса (Qdrant / in-memory).

Отделяет Qdrant от доменной логики. In-memory вариант используется в тестах.
Коллекция создаётся на версию эмбеддинг-модели, чтобы не смешивать векторы.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from personal_hub.config import get_settings


@dataclass
class VectorPoint:
    """Точка в векторном индексе."""

    id: str
    vector: list[float]
    payload: dict


@dataclass
class SearchHit:
    """Результат поиска по векторному индексу."""

    id: str
    score: float
    payload: dict


class VectorStore(Protocol):
    """Контракт векторного хранилища."""

    async def ensure_collection(self, collection: str, vector_size: int) -> None: ...
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None: ...
    async def search(
        self, collection: str, vector: list[float], top_k: int
    ) -> list[SearchHit]: ...
    async def delete_points(self, collection: str, ids: list[str]) -> None: ...


class QdrantVectorStore:
    """Реализация на Qdrant."""

    def __init__(self, url: str) -> None:
        from qdrant_client import models

        self._url = url
        self._models = models

    def _client(self):
        from qdrant_client import AsyncQdrantClient

        return AsyncQdrantClient(url=self._url)

    async def ensure_collection(self, collection: str, vector_size: int) -> None:
        async with self._client() as client:
            if not await client.collection_exists(collection):
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=self._models.VectorParams(
                        size=vector_size, distance=self._models.Distance.COSINE
                    ),
                )

    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        async with self._client() as client:
            await client.upsert(
                collection_name=collection,
                points=[
                    self._models.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                    for p in points
                ],
            )

    async def search(
        self, collection: str, vector: list[float], top_k: int
    ) -> list[SearchHit]:
        async with self._client() as client:
            results = await client.search(
                collection_name=collection, query_vector=vector, limit=top_k
            )
        return [
            SearchHit(id=str(r.id), score=float(r.score), payload=(r.payload or {}))
            for r in results
        ]

    async def delete_points(self, collection: str, ids: list[str]) -> None:
        async with self._client() as client:
            await client.delete(
                collection_name=collection,
                points_selector=self._models.PointIdsList(points=ids),  # type: ignore[arg-type]
            )


class InMemoryVectorStore:
    """In-memory реализация для тестов (cosine similarity)."""

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, VectorPoint]] = {}

    async def ensure_collection(self, collection: str, vector_size: int) -> None:
        self._collections.setdefault(collection, {})

    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        store = self._collections.setdefault(collection, {})
        for p in points:
            store[p.id] = p

    async def search(
        self, collection: str, vector: list[float], top_k: int
    ) -> list[SearchHit]:
        store = self._collections.get(collection, {})
        scored = []
        for point in store.values():
            score = _cosine(vector, point.vector)
            scored.append(SearchHit(id=point.id, score=score, payload=point.payload))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    async def delete_points(self, collection: str, ids: list[str]) -> None:
        store = self._collections.get(collection, {})
        for pid in ids:
            store.pop(pid, None)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Возвращает singleton VectorStore (qdrant или memory для тестов)."""
    global _vector_store
    store = _vector_store
    if store is None:
        settings = get_settings()
        if settings.vector_store_driver == "memory":
            store = InMemoryVectorStore()
        else:
            store = QdrantVectorStore(settings.qdrant_url)
        _vector_store = store
    return store
