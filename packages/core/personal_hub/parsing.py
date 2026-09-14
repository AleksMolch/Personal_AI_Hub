"""Разбор документов в текст (per-page).

Поддерживает TXT/MD (plain), PDF (pypdf) и DOCX (python-docx). Возвращает
список страниц с текстом. Используются permissive-парсеры (не PyMuPDF).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {"txt", "md", "markdown", "pdf", "docx"}


@dataclass
class TextPage:
    """Текст одной страницы/секции документа."""

    page: int
    text: str


class UnsupportedFormatError(Exception):
    """Формат документа не поддерживается."""

    def __init__(self, fmt: str) -> None:
        super().__init__(f"неподдерживаемый формат документа: {fmt}")
        self.code = "UNSUPPORTED_FORMAT"


def _detect_format(filename: str, mime_type: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ext
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }:
        return "docx"
    return ext


def parse_document(filename: str, mime_type: str, data: bytes) -> list[TextPage]:
    """Разбирает документ в список страниц с текстом."""
    fmt = _detect_format(filename, mime_type)
    if fmt == "pdf":
        return _parse_pdf(data)
    if fmt == "docx":
        return _parse_docx(data)
    if fmt in {"txt", "md", "markdown"}:
        return [TextPage(page=1, text=data.decode("utf-8", errors="replace"))]
    raise UnsupportedFormatError(fmt)


def _parse_pdf(data: bytes) -> list[TextPage]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    texts: list[str] = []
    empty_pages: list[int] = []
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        texts.append(text)
        if not text:
            empty_pages.append(index + 1)  # 1-based

    # Для сканированных (без текстового слоя) страниц — OCR.
    if empty_pages:
        ocr = _ocr_pages(data, empty_pages)
        for page_num, text in ocr.items():
            texts[page_num - 1] = text

    pages: list[TextPage] = []
    for index, text in enumerate(texts, start=1):
        if text.strip():
            pages.append(TextPage(page=index, text=text))
    return pages or [TextPage(page=1, text="")]


def _ocr_pages(data: bytes, page_indices: list[int]) -> dict[int, str]:
    """OCR заданных страниц PDF. Ошибки OCR не пробрасываются (asset не портится)."""
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        start = min(page_indices)
        end = max(page_indices)
        images = convert_from_bytes(data, first_page=start, last_page=end)
        result: dict[int, str] = {}
        for offset, image in enumerate(images):
            page_num = start + offset
            if page_num in page_indices:
                result[page_num] = pytesseract.image_to_string(image, lang="rus+eng") or ""
        return result
    except Exception:
        return {}


def _parse_docx(data: bytes) -> list[TextPage]:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # Таблицы тоже извлекаем (простой вариант — по строкам).
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    text = "\n".join(parts)
    return [TextPage(page=1, text=text)]
