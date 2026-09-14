"""Тесты разбора документов (TXT/MD/DOCX) и неподдерживаемого формата."""
from __future__ import annotations

import io

import pytest

from personal_hub.parsing import UnsupportedFormatError, parse_document


def test_parse_txt() -> None:
    pages = parse_document("note.txt", "text/plain", b"hello world")
    assert len(pages) == 1
    assert pages[0].page == 1
    assert pages[0].text == "hello world"


def test_parse_markdown() -> None:
    pages = parse_document("doc.md", "text/markdown", b"# Title\n\nBody")
    assert pages[0].text == "# Title\n\nBody"


def test_parse_docx() -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("Hello from docx")
    buf = io.BytesIO()
    document.save(buf)

    pages = parse_document("test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buf.getvalue())
    assert len(pages) == 1
    assert "Hello from docx" in pages[0].text


def test_unsupported_format() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_document("file.exe", "application/octet-stream", b"binary")
