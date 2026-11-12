"""Golden-тесты структурного чанкинга по заголовкам Markdown."""
from __future__ import annotations

from personal_hub.chunking import chunk_document
from personal_hub.parsing import TextPage

_FIXTURE = """# Введение
Это первый абзац введения.

## Методы
Здесь описан метод активации: введите лицензионный ключ.

### Шаги
Первый шаг — скачать дистрибутив.
"""


def test_headings_split_into_sections() -> None:
    """Каждый заголовок начинает свой чанк, а не сливается с предыдущим."""
    chunks = chunk_document([TextPage(page=1, text=_FIXTURE)])

    texts = [c.text for c in chunks]
    assert any(t.startswith("# Введение") for t in texts)
    assert any(t.startswith("## Методы") for t in texts)
    assert any(t.startswith("### Шаги") for t in texts)


def test_heading_context_prepended_to_chunk() -> None:
    """Заголовок подмешивается в начало чанка для контекста модели."""
    chunks = chunk_document([TextPage(page=1, text=_FIXTURE)])

    methods = next(c for c in chunks if "Методы" in c.text and "лицензионный" in c.text)
    assert methods.text.startswith("## Методы")


def test_no_headings_preserves_flat_chunking() -> None:
    """Текст без заголовков чанкуется как раньше (один плоский поток)."""
    text = "слово " * 1000
    chunks = chunk_document([TextPage(page=1, text=text)], chunk_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    assert all(not c.text.startswith("#") for c in chunks)


def test_empty_heading_section_is_skipped() -> None:
    """Заголовок без тела не порождает пустой чанк."""
    chunks = chunk_document([TextPage(page=1, text="# Только заголовок\n\n# С телом\nТекст")])
    assert all(c.text.strip() for c in chunks)
