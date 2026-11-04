"""Тесты клиента headless-рендера (`pricebot`).

Проверяют: успешный рендер, защиту от SSRF до обращения к сервису, обработку
ошибок сервиса и пустой страницы (заглушка вместо тарифов).
"""
from __future__ import annotations

import json

import pytest

from personal_hub.pricebot import render_page
from personal_hub.pricing_import import PriceImportError


def _service(mock_provider) -> str:
    """Адрес mock-сервера, играющего роль сервиса pricebot."""
    host, port = mock_provider.server_address
    return f"http://{host}:{port}"


def _handler(status: int, payload: dict):
    """Обработчик POST /render для mock-сервера."""

    def handler(_method: str, _path: str, _body: bytes):
        return (status, json.dumps(payload))

    return handler


@pytest.mark.asyncio
async def test_render_returns_text(mock_provider) -> None:
    """Сервис вернул текст — клиент отдаёт его без изменений."""
    mock_provider.spec["POST /render"] = _handler(
        200, {"text": "1M OUTPUT TOKENS $0.6"}
    )

    text = await render_page("https://example.com/pricing", service_url=_service(mock_provider))

    assert text == "1M OUTPUT TOKENS $0.6"


@pytest.mark.asyncio
async def test_render_rejects_internal_url_before_calling_service(mock_provider) -> None:
    """Внутренний адрес отсекается ещё до запроса к сервису рендера."""
    called: list[str] = []

    def handler(_method: str, _path: str, _body: bytes):
        called.append("render")
        return (200, json.dumps({"text": "ok"}))

    mock_provider.spec["POST /render"] = handler

    with pytest.raises(PriceImportError) as exc_info:
        await render_page("http://127.0.0.1:8000/api", service_url=_service(mock_provider))

    assert exc_info.value.code == "PRICE_IMPORT_FORBIDDEN_HOST"
    assert called == []


@pytest.mark.asyncio
async def test_render_service_error(mock_provider) -> None:
    """Ошибка сервиса превращается в стабильный код с пояснением."""
    mock_provider.spec["POST /render"] = _handler(
        500, {"error": "Navigation timeout"}
    )

    with pytest.raises(PriceImportError) as exc_info:
        await render_page("https://example.com/pricing", service_url=_service(mock_provider))

    assert exc_info.value.code == "PRICEBOT_FAILED"
    assert "Navigation timeout" in exc_info.value.message


@pytest.mark.asyncio
async def test_render_empty_page(mock_provider) -> None:
    """Пустой текст — отдельный код: вероятно, сайт показал заглушку."""
    mock_provider.spec["POST /render"] = _handler(200, {"text": "   "})

    with pytest.raises(PriceImportError) as exc_info:
        await render_page("https://example.com/pricing", service_url=_service(mock_provider))

    assert exc_info.value.code == "PRICEBOT_EMPTY"


@pytest.mark.asyncio
async def test_render_unreachable_service() -> None:
    """Недоступный сервис даёт понятную подсказку про профиль compose."""
    with pytest.raises(PriceImportError) as exc_info:
        await render_page("https://example.com/pricing", service_url="http://127.0.0.1:1")

    assert exc_info.value.code == "PRICEBOT_UNREACHABLE"
    assert "pricebot" in exc_info.value.message
