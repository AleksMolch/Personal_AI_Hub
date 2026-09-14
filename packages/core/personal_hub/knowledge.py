"""Общие утилиты RAG/базы знаний.

Имя коллекции зависит от id базы и версии эмбеддинг-модели, чтобы смена
модели создавала новый индекс, не смешивая векторы.
"""
from __future__ import annotations

import hashlib
import uuid

# Порог релевантности (cosine): ниже — источники считаются недостаточными.
MIN_RELEVANCE = 0.30


def collection_name(knowledge_base_id: uuid.UUID, embedding_version: str) -> str:
    """Имя коллекции: kb + id + хэш версии эмбеддинга."""
    version_hash = hashlib.sha1(embedding_version.encode()).hexdigest()[:12]
    return f"kb_{knowledge_base_id.hex[:12]}_{version_hash}"
