"""Чанкинг текста для RAG: окно по символам с учётом заголовков Markdown.

Разбивает страницы на пересекающиеся чанки фиксированного размера (по
символам, ~1 токен на 4 символа) с overlap. Если в тексте есть заголовки
Markdown (`#`…`######`), разбиение сначала идёт по секциям, а заголовок
подмешивается в начало каждого чанка: так ответ модели сохраняет контекст
«в какой части документа мы находимся» и лучше матчится по ключевым словам
заголовка. Каждый чанк хранит номер страницы и позицию для цитирования.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from personal_hub.parsing import TextPage

CHUNK_CHARS = 2000
OVERLAP_CHARS = 200

# Заголовок Markdown: 1–6 решёток + пробел + текст (в начале строки).
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


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


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Разбивает текст на секции по заголовкам Markdown.

    Возвращает список `(заголовок, тело)`; заголовок пуст, если заголовков нет
    (тогда весь текст — одна секция). Текст до первого заголовка тоже
    сохраняется как секция с пустым заголовком.
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_heading = ""
    body: list[str] = []
    has_heading = False

    for line in lines:
        match = _HEADING_RE.match(line.strip())
        if match:
            has_heading = True
            if body or current_heading:
                sections.append((current_heading, "\n".join(body)))
            current_heading = f"{match.group(1)} {match.group(2)}"
            body = []
        else:
            body.append(line)

    if body or current_heading:
        sections.append((current_heading, "\n".join(body)))
    if not has_heading:
        # Заголовков нет — возвращаем исходный текст одним куском.
        return [("", text)]
    return sections


def chunk_document(
    pages: list[TextPage],
    chunk_chars: int = CHUNK_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[ChunkData]:
    """Возвращает чанки документа с локацией и checksum.

    При наличии заголовков Markdown каждая секция чанкуется отдельно, а
    заголовок секции подмешивается в начало чанка (контекст + лучший матч по
    ключевым словам заголовка).
    """
    chunks: list[ChunkData] = []
    position = 0
    for page in pages:
        for heading, body in _split_sections(page.text):
            if not body.strip():
                continue
            prefix = f"{heading}\n" if heading else ""
            for piece in _split(body, chunk_chars, overlap_chars):
                text = (prefix + piece).strip()
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
