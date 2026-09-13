"""Нормализация ошибок провайдеров в стабильные коды приложения.

UI зависит от `code`, а не от текста стороннего сервиса. Код + retryable
позволяют единообразно обрабатывать 401/402/429/5xx от разных провайдеров.
"""
from __future__ import annotations


class ProviderError(Exception):
    """Нормализованная ошибка провайдера со стабильным кодом."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# Отображение HTTP-статуса в нормализованный код.
_STATUS_MAP: dict[int, tuple[str, bool]] = {
    401: ("PROVIDER_UNAUTHORIZED", False),
    402: ("PROVIDER_INSUFFICIENT_BALANCE", False),
    403: ("PROVIDER_FORBIDDEN", False),
    404: ("MODEL_NOT_FOUND", False),
    408: ("PROVIDER_TIMEOUT", True),
    429: ("PROVIDER_RATE_LIMITED", True),
}


def normalize_http_status(status_code: int, detail: str = "") -> ProviderError:
    """Преобразует HTTP-статус провайдера в ProviderError.

    Неизвестные 4xx/5xx сводятся к PROVIDER_ERROR; секреты в detail не
    передаются вызывающим кодом.
    """
    if status_code in _STATUS_MAP:
        code, retryable = _STATUS_MAP[status_code]
        return ProviderError(code, detail or code, retryable)
    if 500 <= status_code < 600:
        return ProviderError("PROVIDER_ERROR", detail or "Ошибка провайдера", True)
    return ProviderError("PROVIDER_ERROR", detail or f"HTTP {status_code}", False)
