"""Гибридный поиск и лёгкий reranking для RAG.

Объединяет dense-score (косинус из VectorStore) с lexical-совпадением ключевых
слов запроса и текста чанка линейно: итоговый score = 0.5·dense + 0.5·lexical.
Это поднимает чанки с точными терминами запроса, даже если их векторный score
ниже среднего (например, редкие термины или названия из заголовков).

Не зависит от Qdrant full-text индекса: lexical-score считается по уже
извлечённому плотному кандидатному множеству, поэтому работает на любом
VectorStore и полностью unit-тестируем.
"""
from __future__ import annotations

import re

# Вес dense против lexical. 0.5 — сбалансированный вариант.
_DENSE_WEIGHT = 0.5
_LEXICAL_WEIGHT = 0.5

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Строит множество нормализованных токенов текста."""
    return set(_TOKEN_RE.findall(text.lower()))


def lexical_score(query: str, text: str) -> float:
    """Доля токенов запроса, встретившихся в тексте (0..1)."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = _tokens(text)
    return len(query_tokens & text_tokens) / len(query_tokens)


def hybrid_rerank(
    query: str,
    items: list[tuple[str, str, float]],
    top_k: int,
) -> list[tuple[str, str]]:
    """Переранжирует тройки (id, text, dense_score) по fusion-оценке.

    `dense_score` — косинусная близость из VectorStore (может быть любой).
    Возвращает не более `top_k` пар `(id, text)` в новом порядке.
    """
    if not items:
        return []

    def _norm(score: float) -> float:
        """Приводит dense-score к [0, 1] (косинус может быть отрицательным)."""
        return max(0.0, min(1.0, score))

    scored = [
        (
            item_id,
            text,
            _DENSE_WEIGHT * _norm(dense_score) + _LEXICAL_WEIGHT * lexical_score(query, text),
        )
        for item_id, text, dense_score in items
    ]
    scored.sort(key=lambda item: item[2], reverse=True)
    return [(item_id, text) for item_id, text, _score in scored[:top_k]]
