"""Unit-тесты гибридного reranking (dense + lexical, score fusion)."""
from __future__ import annotations

from personal_hub.retrieval import hybrid_rerank, lexical_score


def test_lexical_score_full_match() -> None:
    assert lexical_score("ключ активации", "лицензионный ключ активации") == 1.0


def test_lexical_score_partial_match() -> None:
    assert lexical_score("ключ активации", "лицензионный ключ") == 0.5


def test_hybrid_rerank_promotes_exact_lexical_match() -> None:
    """Чанк с точными терминами поднимается выше плотного лидера с тем же score."""
    query = "лицензионный ключ активации"
    items = [
        ("a", "Общие сведения о продукте и его возможностях", 0.9),
        ("b", "лицензионный ключ активации выдаётся после оплаты", 0.5),
    ]

    result = hybrid_rerank(query, items, top_k=2)

    assert [item_id for item_id, _ in result][0] == "b"


def test_hybrid_rerank_empty() -> None:
    assert hybrid_rerank("q", [], top_k=5) == []


def test_hybrid_rerank_respects_top_k() -> None:
    items = [("a", "текст один", 0.9), ("b", "текст два", 0.8), ("c", "текст три", 0.7)]
    result = hybrid_rerank("текст", items, top_k=2)
    assert len(result) == 2
