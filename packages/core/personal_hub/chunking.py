"""Чанкинг текста для RAG.

Разбивает страницы на пересекающиеся чанки фиксированного размера (по
символам, ~1 токен на 4 символа) с overlap. Каждый чанк сохраняет номер
страницы и позицию для цитирования.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from personal_hub.parsing import TextPage

CHUNK_CHARS = 2000
OVERLAP_CHARS = 200


@dataclass
class ChunkData:
    """Чанк текста с метаданными локации и checksum."""

    text: str
    page: int | None
    position: int
    checksum: str


def _split(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    """Разбивает текст на пересекающиеся чанки (sliding window)."""
    if len(text) <= chunk_chars:
        return [text] if text.strip() else []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_chars, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = end - overlap_chars
    return chunks


def chunk_document(
    pages: list[TextPage],
    chunk_chars: int = CHUNK_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[ChunkData]:
    """Возвращает чанки документа с локацией и checksum."""
    chunks: list[ChunkData] = []
    position = 0
    for page in pages:
        for piece in _split(page.text, chunk_chars, overlap_chars):
            text = piece.strip()
            if not text:
                continue
            chunks.append(
                ChunkData(
                    text=text,
                    page=page.page,
                    position=position,
                    checksum=hashlib.sha256(text.encode()).hexdigest(),
                )
            )
            position += 1
    return chunks
