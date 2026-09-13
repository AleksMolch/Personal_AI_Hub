"""Тесты нормализации ошибок провайдеров.

Проверяют стабильные коды и флаги retryable для HTTP-статусов.
"""
from __future__ import annotations

import pytest

from personal_hub.providers.errors import ProviderError, normalize_http_status


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "PROVIDER_UNAUTHORIZED", False),
        (402, "PROVIDER_INSUFFICIENT_BALANCE", False),
        (403, "PROVIDER_FORBIDDEN", False),
        (404, "MODEL_NOT_FOUND", False),
        (408, "PROVIDER_TIMEOUT", True),
        (429, "PROVIDER_RATE_LIMITED", True),
        (500, "PROVIDER_ERROR", True),
        (502, "PROVIDER_ERROR", True),
    ],
)
def test_normalize_status(status: int, code: str, retryable: bool) -> None:
    err = normalize_http_status(status)
    assert err.code == code
    assert err.retryable == retryable
    assert isinstance(err, ProviderError)


def test_normalize_unknown_4xx() -> None:
    err = normalize_http_status(418)
    assert err.code == "PROVIDER_ERROR"
    assert err.retryable is False
