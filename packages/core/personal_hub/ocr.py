"""OCR-бэкенды для сканов документов (Tesseract / RapidOCR).

Назначение: централизовать OCR за единым интерфейсом `OcrBackend`. Текущий
Tesseract-путь сохраняет поведение, RapidOCR добавляется как ленивый
альтернативный backend (worker-only). Выбор backend — через настройки
`OCR_BACKEND=tesseract|rapidocr|auto`; режим `auto` использует RapidOCR при
его доступности и откатывается на Tesseract.

Функции: `get_ocr_backend()` (выбор по настройкам), `recognize_image()`
(распознавание одной картинки с лимитами и таймаутом), `ocr_pdf_pages()`
(рендер пустых страниц PDF через poppler и их распознавание).

Зависимости: lazy import pytesseract/pdf2image и rapidocr_onnxruntime — модуль
не тянет тяжёлые библиотеки при старте API. Ошибки OCR поднимаются как
`OcrError` со стабильными кодами (OCR_UNAVAILABLE/OCR_FAILED/OCR_TIMEOUT) и
должны быть видны в статусе задачи, а не проглатываться.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Protocol

from personal_hub.config import get_settings

# Общий executor: один воркер, чтобы OCR-потоки не копились при таймаутах.
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")


class OcrError(Exception):
    """Ошибка OCR со стабильным кодом для статуса задачи."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OcrResult:
    """Результат распознавания одной страницы/изображения."""

    __slots__ = ("text", "warnings")

    def __init__(self, text: str, warnings: list[str] | None = None) -> None:
        self.text = text
        self.warnings = warnings or []


class OcrBackend(Protocol):
    """Контракт OCR-бэкенда: доступен ли рантайм и распознать картинку.

    `image` — изображение PIL (Image), математика бэкенда сама решает, как его
    преобразовать. Распознавание выполняется в отдельном потоке executor'а.
    """

    name: str

    def is_available(self) -> bool: ...
    def recognize(self, image: Any, languages: list[str]) -> OcrResult: ...


def parse_languages(value: str) -> list[str]:
    """Разбирает строку языков "rus,eng" в список ["rus", "eng"]."""
    return [part.strip() for part in value.split(",") if part.strip()]


class TesseractOcrBackend:
    """OCR через tesseract (pytesseract + traineddata ru/eng в образе)."""

    name = "tesseract"

    def __init__(self) -> None:
        self._checked: bool | None = None

    def is_available(self) -> bool:
        if self._checked is None:
            try:
                import pytesseract

                pytesseract.get_tesseract_version()
                self._checked = True
            except Exception:
                self._checked = False
        return self._checked

    def recognize(self, image: Any, languages: list[str]) -> OcrResult:
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrError("OCR_UNAVAILABLE", "pytesseract не установлен.") from exc

        lang = "+".join(languages) if languages else None
        kwargs: dict[str, str] = {}
        if lang:
            kwargs["lang"] = lang
        try:
            # Блокирующий вызов выполняется в OCR_EXECUTOR (см. recognize_image).
            text = pytesseract.image_to_string(image, **kwargs)
        except Exception as exc:
            raise OcrError("OCR_FAILED", f"Сбой Tesseract: {exc}") from exc
        return OcrResult(text=text or "")


class RapidOcrBackend:
    """OCR через RapidOCR (ONNX). Инициализируется лениво и только по вызову.

    Модели идут с пакетом rapidocr_onnxruntime; на Этапе 1 пакет не включён в
    базовые зависимости, поэтому `is_available()` возвращает False в обычном
    образе и `auto` откатывается на Tesseract. Русскоязычные сканы могут
    требовать многоязычных моделей PP-OCR ml (вне скоупа загрузки по умолчанию).
    """

    name = "rapidocr"

    def __init__(self) -> None:
        self._checked: bool | None = None
        self._engine: Any = None

    def is_available(self) -> bool:
        if self._checked is None:
            try:
                import rapidocr_onnxruntime  # noqa: F401

                self._checked = True
            except ImportError:
                # Пакет может быть установлен, но без системных библиотек
                # OpenCV (libGL.so.1) — такой backend считаем недоступным.
                self._checked = False
        return self._checked

    def recognize(self, image: Any, languages: list[str]) -> OcrResult:
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            # Первопричина в тексте: часто пакет установлен, но не хватает
            # системных библиотек OpenCV (libGL.so.1/libglib2.0-0) — без
            # детали диагностика упирается в «переустановите пакет».
            raise OcrError(
                "OCR_UNAVAILABLE",
                f"RapidOCR недоступен ({exc}). Установите rapidocr_onnxruntime "
                "и системные пакеты libgl1 + libglib2.0-0 в worker-образ "
                "или переключите OCR_BACKEND=tesseract.",
            ) from exc

        try:
            if self._engine is None:
                # Однократная инициализация ONNX-моделей (worker only).
                self._engine = RapidOCR()
            result, _ = self._engine(np.asarray(image))
        except Exception as exc:
            raise OcrError("OCR_FAILED", f"Сбой RapidOCR: {exc}") from exc

        lines = [entry[1] for entry in (result or []) if len(entry) > 1]
        return OcrResult(text="\n".join(lines))


def get_ocr_backend() -> OcrBackend:
    """Возвращает OCR-бэкенд по настройке OCR_BACKEND.

    Режимы:
    - tesseract — только Tesseract (по умолчанию);
    - rapidocr — только RapidOCR (ошибка при отсутствии пакета);
    - auto — RapidOCR при доступности, иначе Tesseract.
    Неизвестный режим -> ValueError (конфигурационная ошибка).
    """
    mode = get_settings().ocr_backend
    if mode == "rapidocr":
        backend: OcrBackend = RapidOcrBackend()
        if not backend.is_available():
            raise OcrError(
                "OCR_UNAVAILABLE",
                "RapidOCR недоступен: установите rapidocr_onnxruntime в образ.",
            )
        return backend
    if mode == "auto":
        rapid: OcrBackend = RapidOcrBackend()
        if rapid.is_available():
            return rapid
        tesseract: OcrBackend = TesseractOcrBackend()
        if not tesseract.is_available():
            raise OcrError(
                "OCR_UNAVAILABLE", "Ни один OCR-бэкенд недоступен (tesseract/rapidocr)."
            )
        return tesseract
    if mode == "tesseract":
        backend = TesseractOcrBackend()
        if not backend.is_available():
            raise OcrError(
                "OCR_UNAVAILABLE", "Tesseract недоступен: проверьте tesseract-ocr."
            )
        return backend
    raise ValueError(f"неизвестный OCR_BACKEND: {mode}")


def _downscale(image: Any, max_side: int) -> Any:
    """Уменьшает изображение, чтобы сторона не превышала лимит (без искажений)."""
    if image is None or max_side <= 0:
        return image
    width, height = image.size
    if max(width, height) <= max_side:
        return image
    copy = image.copy()
    copy.thumbnail((max_side, max_side))
    return copy


def recognize_image(
    image: Any,
    languages: list[str],
    backend: OcrBackend | None = None,
    timeout: float | None = None,
) -> OcrResult:
    """Распознаёт один image с таймаутом на страницу через выделенный поток.

    Порядок защиты от зависания: singleton-executor с одним воркером, чтобы в
    очередь не копились параллельные OCR; таймаут поднимает OcrError(OCR_TIMEOUT).
    Зависший поток продолжает работу в фоне, но занимает единственный воркер
    (ресурс ограничен), что является документированным компромиссом.
    """
    backend = backend or get_ocr_backend()
    settings = get_settings()
    scaled = _downscale(image, settings.ocr_max_image_side)
    timeout = timeout or settings.ocr_page_timeout_seconds
    future = _OCR_EXECUTOR.submit(backend.recognize, scaled, languages)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        raise OcrError(
            "OCR_TIMEOUT",
            f"Превышено время распознавания страницы ({timeout:g} c).",
        ) from None


def ocr_pdf_pages(data: bytes, page_indices: list[int]) -> dict[int, str]:
    """Распознаёт пустые страницы PDF-скана; возвращает {page_num: text}.

    Ограничения: распознаётся не более `OCR_MAX_PAGES` страниц. Ошибки OCR
    не проглатываются: поднимается OcrError, чтобы задача индексации получила
    видимый code.
    """
    settings = get_settings()
    limited = page_indices[: settings.ocr_max_pages] if settings.ocr_max_pages else page_indices
    if not limited:
        return {}

    try:
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise OcrError(
            "OCR_UNAVAILABLE", "pdf2image не установлен (нужен poppler)."
        ) from exc

    start = min(limited)
    end = max(limited)
    try:
        images = convert_from_bytes(data, first_page=start, last_page=end)
    except Exception as exc:
        raise OcrError("OCR_FAILED", f"Не удалось отрендерить страницы: {exc}") from exc

    backend = get_ocr_backend()
    languages = parse_languages(settings.ocr_languages)
    result: dict[int, str] = {}
    for offset, image in enumerate(images):
        page_num = start + offset
        if page_num not in limited:
            continue
        text = recognize_image(image, languages, backend=backend)
        if text.text:
            result[page_num] = text.text
    return result
