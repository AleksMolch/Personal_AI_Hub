"""Тесты чанкинга: разбиение, overlap, локация и checksum."""
from __future__ import annotations

import hashlib

from personal_hub.chunking import chunk_document
from personal_hub.parsing import TextPage


def test_single_small_chunk() -> None:
    chunks = chunk_document([TextPage(page=1, text="короткий текст")])
    assert len(chunks) == 1
    assert chunks[0].page == 1
    assert chunks[0].position == 0
    assert chunks[0].checksum == hashlib.sha256("короткий текст".encode()).hexdigest()


def test_splits_long_text() -> None:
    text = "word " * 1000  # ~5000 символов
    chunks = chunk_document([TextPage(page=1, text=text)], chunk_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    # Позиции уникальны и идут по порядку.
    positions = [c.position for c in chunks]
    assert positions == sorted(positions)
    # Каждый чанк не превышает заданного размера (с учётом overlap).
    assert all(len(c.text) <= 1000 for c in chunks)


def test_page_metadata_preserved() -> None:
    pages = [TextPage(page=1, text="A" * 10), TextPage(page=2, text="B" * 10)]
    chunks = chunk_document(pages, chunk_chars=5, overlap_chars=0)
    pages_in = {c.page for c in chunks}
    assert pages_in == {1, 2}
