"""Тесты OCR: парсинг языков, выбор backend, лимиты и таймауты.

Не зависит от установленного tesseract/rapidocr: бэкенды подменяются fake,
чтобы проверять логику выбора/лимитов, а не внешний рантайм.
"""
from __future__ import annotations

import io
import time

import pytest
from personal_hub.config import get_settings
from personal_hub.ocr import (
    OcrError,
    OcrResult,
    RapidOcrBackend,
    TesseractOcrBackend,
    get_ocr_backend,
    ocr_pdf_pages,
    parse_languages,
    recognize_image,
)
from personal_hub.parsing import parse_document
from PIL import Image


class _FakeBackend:
    """Детерминированный OCR-бэкенд для тестов (без внешних движков)."""

    name = "fake"

    def __init__(self, text: str = "OCR FAKE TEXT") -> None:
        self.text = text
        self.images: list = []

    def is_available(self) -> bool:
        return True

    def recognize(self, image, languages: list[str]) -> OcrResult:
        self.images.append(image)
        return OcrResult(text=self.text, warnings=[])


def _settings():
    return get_settings()


def test_parse_languages() -> None:
    assert parse_languages("rus, eng") == ["rus", "eng"]
    assert parse_languages("") == []
    assert parse_languages("eng") == ["eng"]


def test_backend_selection_tesseract(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "tesseract")
    monkeypatch.setattr(TesseractOcrBackend, "is_available", lambda self: True)
    backend = get_ocr_backend()
    assert isinstance(backend, TesseractOcrBackend)


def test_backend_selection_rapidocr(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "rapidocr")
    monkeypatch.setattr(RapidOcrBackend, "is_available", lambda self: True)
    backend = get_ocr_backend()
    assert isinstance(backend, RapidOcrBackend)


def test_backend_auto_falls_back_to_tesseract(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "auto")
    monkeypatch.setattr(RapidOcrBackend, "is_available", lambda self: False)
    monkeypatch.setattr(TesseractOcrBackend, "is_available", lambda self: True)
    backend = get_ocr_backend()
    assert isinstance(backend, TesseractOcrBackend)


def test_backend_auto_uses_rapidocr_if_available(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "auto")
    monkeypatch.setattr(RapidOcrBackend, "is_available", lambda self: True)
    backend = get_ocr_backend()
    assert isinstance(backend, RapidOcrBackend)


def test_backend_unavailable_raises(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "rapidocr")
    monkeypatch.setattr(RapidOcrBackend, "is_available", lambda self: False)
    with pytest.raises(OcrError) as exc_info:
        get_ocr_backend()
    assert exc_info.value.code == "OCR_UNAVAILABLE"


def test_rapidocr_import_failure_reports_root_cause(monkeypatch) -> None:
    """Ошибка импорта RapidOCR должна показывать первопричину (например, libGL)."""
    import sys

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    monkeypatch.setattr(RapidOcrBackend, "is_available", lambda self: True)
    with pytest.raises(OcrError) as exc_info:
        RapidOcrBackend().recognize(Image.new("RGB", (10, 10), "white"), ["rus"])
    assert exc_info.value.code == "OCR_UNAVAILABLE"
    # Причина из исходного исключения попадает в текст: иначе диагностика
    # упирается в «переустановите пакет» даже при нехватке libGL.so.1.
    assert "halted" in exc_info.value.message
    assert "libgl1" in exc_info.value.message


def test_unknown_backend_raises_value_error(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_backend", "magic")
    with pytest.raises(ValueError):
        get_ocr_backend()


def test_max_pages_zero_disables_pdf_ocr(monkeypatch) -> None:
    """OCR_MAX_PAGES=0 отключает OCR: рендер страниц не вызывается."""
    monkeypatch.setattr(_settings(), "ocr_max_pages", 0)

    import pdf2image

    def _must_not_render(*args, **kwargs):
        raise AssertionError("рендер не должен вызываться при OCR_MAX_PAGES=0")

    monkeypatch.setattr(pdf2image, "convert_from_bytes", _must_not_render)
    result = ocr_pdf_pages(b"fake pdf bytes", [1, 2])
    assert result.texts == {}
    assert result.failed == {}


def test_image_ocr_disabled_when_max_pages_zero(monkeypatch) -> None:
    """При OCR_MAX_PAGES=0 изображения не распознаются (OCR_DISABLED)."""
    monkeypatch.setattr(_settings(), "ocr_max_pages", 0)
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")

    with pytest.raises(OcrError) as exc_info:
        parse_document("photo.png", "image/png", buf.getvalue())
    assert exc_info.value.code == "OCR_DISABLED"


def test_image_pixel_cap_rejects_huge_image(monkeypatch) -> None:
    """Пиксельный лимит срабатывает до декодирования (защита от bomb)."""
    monkeypatch.setattr(_settings(), "ocr_max_image_pixels", 100)
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    monkeypatch.setattr(
        "personal_hub.ocr.recognize_image",
        lambda *args, **kwargs: pytest.fail("recognize_image не должен вызываться"),
    )

    with pytest.raises(OcrError) as exc_info:
        parse_document("photo.png", "image/png", buf.getvalue())
    assert exc_info.value.code == "OCR_IMAGE_TOO_LARGE"


def test_recognize_image_uses_backend_and_downscales(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_max_image_side", 3500)
    backend = _FakeBackend(text="HELLO OCR")
    big = Image.new("RGB", (4000, 100), "white")
    result = recognize_image(big, ["eng"], backend=backend, timeout=5)
    assert result.text == "HELLO OCR"
    # Крупная сторона уменьшена до лимита, пропорции сохранены.
    scaled = backend.images[0]
    assert scaled.size[0] == 3500
    assert abs(scaled.size[1] / scaled.size[0] - 100 / 4000) < 0.02


def test_recognize_image_timeout(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_page_timeout_seconds", 0.05)

    class _SlowBackend:
        name = "slow"

        def is_available(self) -> bool:
            return True

        def recognize(self, image, languages: list[str]) -> OcrResult:
            time.sleep(0.5)
            return OcrResult(text="late")

    with pytest.raises(OcrError) as exc_info:
        recognize_image(Image.new("RGB", (10, 10)), ["eng"], backend=_SlowBackend())
    assert exc_info.value.code == "OCR_TIMEOUT"


def test_ocr_pdf_pages_respects_max_pages(monkeypatch) -> None:
    monkeypatch.setattr(_settings(), "ocr_max_pages", 3)
    monkeypatch.setattr(_settings(), "ocr_languages", "rus,eng")

    import pdf2image

    def _fake_pdftoppm(*args, **kwargs):
        # Имитация рендера страниц 1..5.
        return [Image.new("RGB", (10, 10), "white") for _ in range(5)]

    monkeypatch.setattr(pdf2image, "convert_from_bytes", _fake_pdftoppm)
    fake = _FakeBackend(text="PAGE TEXT")
    monkeypatch.setattr("personal_hub.ocr.get_ocr_backend", lambda: fake)
    monkeypatch.setattr("personal_hub.ocr.parse_languages", lambda value: ["rus", "eng"])

    result = ocr_pdf_pages(b"fake pdf bytes", [1, 2, 3, 4, 5])
    assert set(result.texts.keys()) == {1, 2, 3}
    assert all(result.texts[k] == "PAGE TEXT" for k in result.texts)
    assert result.failed == {}


def test_ocr_pdf_pages_renders_only_requested_pages(monkeypatch) -> None:
    """Рендер не захватывает пропущенные страницы (иначе PDF рендерится целиком).

    Разрозненные пустые страницы (например, 1 и 500 в PDF на 500 страниц)
    должны рендериться отдельными вызовами: старый код рендерил диапазон
    min..max и загружал в RAM сотни страниц, которые OCR не нужны.
    """
    monkeypatch.setattr(_settings(), "ocr_max_pages", 10)
    monkeypatch.setattr(_settings(), "ocr_languages", "rus,eng")

    import pdf2image

    calls: list[tuple[int, int]] = []

    def _fake_convert(data, first_page=None, last_page=None, **kwargs):
        calls.append((first_page, last_page))
        count = (last_page or 1) - (first_page or 1) + 1
        return [Image.new("RGB", (10, 10), "white") for _ in range(count)]

    monkeypatch.setattr(pdf2image, "convert_from_bytes", _fake_convert)
    fake = _FakeBackend(text="PAGE TEXT")
    monkeypatch.setattr("personal_hub.ocr.get_ocr_backend", lambda: fake)

    result = ocr_pdf_pages(b"fake pdf bytes", [1, 500])

    rendered: set[int] = set()
    for first, last in calls:
        rendered.update(range(first, last + 1))
    assert rendered == {1, 500}
    assert set(result.texts) == {1, 500}


def test_parse_image_document(monkeypatch) -> None:
    """Изображение проходит OCR-ветку парсинга документов."""
    from personal_hub.ocr import OcrResult

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")

    monkeypatch.setattr(
        "personal_hub.ocr.recognize_image",
        lambda image, languages: OcrResult(text="IMG TEXT", warnings=[]),
    )
    document = parse_document("photo.png", "image/png", buf.getvalue())
    assert len(document.pages) == 1
    assert document.pages[0].page == 1
    assert document.pages[0].text == "IMG TEXT"
    assert document.warnings == []


def test_ocr_pdf_pages_partial_failure_keeps_good_pages(monkeypatch) -> None:
    """Сбой одной страницы не отменяет распознавание остальных."""
    monkeypatch.setattr(_settings(), "ocr_max_pages", 10)
    monkeypatch.setattr(_settings(), "ocr_languages", "rus,eng")

    import pdf2image

    def _fake_convert(data, first_page=None, last_page=None, **kwargs):
        count = (last_page or 1) - (first_page or 1) + 1
        return [Image.new("RGB", (10, 10), "white") for _ in range(count)]

    monkeypatch.setattr(pdf2image, "convert_from_bytes", _fake_convert)
    calls = {"n": 0}

    class _FlakyBackend:
        name = "flaky"

        def is_available(self) -> bool:
            return True

        def recognize(self, image, languages: list[str]) -> OcrResult:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OcrError("OCR_TIMEOUT", "таймаут страницы")
            return OcrResult(text="PAGE TEXT")

    monkeypatch.setattr("personal_hub.ocr.get_ocr_backend", lambda: _FlakyBackend())
    monkeypatch.setattr("personal_hub.ocr.parse_languages", lambda value: ["rus", "eng"])

    result = ocr_pdf_pages(b"fake pdf bytes", [1, 2])
    assert result.texts == {2: "PAGE TEXT"}
    assert result.failed == {1: "OCR_TIMEOUT"}


def test_ocr_pdf_pages_all_failed_raises(monkeypatch) -> None:
    """Если ни одна страница не распознана — ошибка не прячется."""
    monkeypatch.setattr(_settings(), "ocr_max_pages", 10)
    monkeypatch.setattr(_settings(), "ocr_languages", "rus,eng")

    import pdf2image

    def _fake_convert(data, first_page=None, last_page=None, **kwargs):
        return [Image.new("RGB", (10, 10), "white")]

    monkeypatch.setattr(pdf2image, "convert_from_bytes", _fake_convert)

    class _BrokenBackend:
        name = "broken"

        def is_available(self) -> bool:
            return True

        def recognize(self, image, languages: list[str]) -> OcrResult:
            raise OcrError("OCR_FAILED", "движок сломан")

    monkeypatch.setattr("personal_hub.ocr.get_ocr_backend", lambda: _BrokenBackend())
    monkeypatch.setattr("personal_hub.ocr.parse_languages", lambda value: ["rus", "eng"])

    with pytest.raises(OcrError) as exc_info:
        ocr_pdf_pages(b"fake pdf bytes", [1])
    assert exc_info.value.code == "OCR_FAILED"
