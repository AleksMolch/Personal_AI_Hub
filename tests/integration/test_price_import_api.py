"""Интеграционные тесты импорта тарифов: режимы LLM и рендера.

Проверяют денежную часть (резерв до вызова, UsageRecord, отказ при
превышении бюджета) и то, что сбой не приводит к платному вызову.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from personal_hub.config import get_settings

_PRICES_HTML = (
    "<table><tr><th>1M INPUT TOKENS (CACHE MISS)</th>"
    "<th>1M OUTPUT TOKENS</th></tr>"
    "<tr><td>$0.15</td><td>$0.6</td></tr></table>"
)

_LLM_JSON = (
    '{"input_per_million": 0.15, "output_per_million": 0.6, '
    '"cache_read_per_million": null, "cache_write_per_million": null}'
)


async def _setup(client: AsyncClient, mock_provider, *, with_price: bool = True):
    """Готовит администратора, провайдера, модель и (опционально) цену."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "deepseek-flash", "name": "Flash"}]}),
    )
    provider = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "DeepSeek",
            "base_url": f"http://{host}:{port}",
            "api_key": "sk-test",
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/providers/{provider.json()['id']}/sync-models", headers=headers
    )
    model_id = (await client.get("/api/v1/models", headers=headers)).json()[0]["id"]
    if with_price:
        await client.post(
            "/api/v1/prices",
            json={
                "model_profile_id": model_id,
                "input_per_million": "0.15",
                "output_per_million": "0.6",
                "currency": "USD",
            },
            headers=headers,
        )
    return headers, model_id


def _patch_fetch(monkeypatch, html: str = _PRICES_HTML) -> None:
    """Подменяет загрузку страницы: SSRF-фильтр не пускает тесты на localhost."""

    async def fake_fetch(_url: str) -> str:
        return html

    monkeypatch.setattr("app.api.prices.fetch_pricing_page", fake_fetch)


def _chat_handler(content: str, usage: dict | None = None):
    """Мок чата: возвращает заданный текст и usage."""

    def handler(_method: str, _path: str, _body: bytes):
        body = {"choices": [{"message": {"content": content}}]}
        if usage:
            body["usage"] = usage
        return (200, json.dumps(body))

    return handler


@pytest.mark.asyncio
async def test_llm_extraction_records_actual_usage(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """LLM-извлечение создаёт UsageRecord с операцией и состоянием actual."""
    headers, model_id = await _setup(client, mock_provider)
    _patch_fetch(monkeypatch)
    mock_provider.spec["POST /chat/completions"] = _chat_handler(
        _LLM_JSON, {"prompt_tokens": 900, "completion_tokens": 40}
    )

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "llm", "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "llm"
    assert body["llm_model"]
    values = {c["field"]: c["value"] for c in body["candidates"]}
    assert values["input_per_million"] == "0.15"
    assert values["output_per_million"] == "0.6"

    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    price_records = [
        r for r in records if r["units_json"].get("operation") == "price_llm_extract"
    ]
    assert len(price_records) == 1
    assert price_records[0]["cost_state"] == "actual"
    assert price_records[0]["units_json"]["input_tokens"] == 900


@pytest.mark.asyncio
async def test_llm_extraction_requires_priced_model(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """Без модели с ценой платный вызов отклоняется, провайдер не вызывается."""
    headers, _ = await _setup(client, mock_provider, with_price=False)
    _patch_fetch(monkeypatch)
    called: list[str] = []

    def handler(_method: str, _path: str, _body: bytes):
        called.append("chat")
        return (200, json.dumps({"choices": [{"message": {"content": _LLM_JSON}}]}))

    mock_provider.spec["POST /chat/completions"] = handler

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "llm"},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "ценой" in resp.json()["error"]["message"]
    assert called == [], "платный вызов не должен уходить без цены"


@pytest.mark.asyncio
async def test_llm_extraction_blocked_by_budget(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """При исчерпанном бюджете провайдер не вызывается, возвращается 402."""
    headers, model_id = await _setup(client, mock_provider)
    _patch_fetch(monkeypatch)
    await client.put(
        "/api/v1/budgets",
        json={"daily_limit": "0.00000001"},
        headers=headers,
    )
    called: list[str] = []

    def handler(_method: str, _path: str, _body: bytes):
        called.append("chat")
        return (200, json.dumps({"choices": [{"message": {"content": _LLM_JSON}}]}))

    mock_provider.spec["POST /chat/completions"] = handler

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "llm", "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "BUDGET_EXCEEDED"
    assert called == []


@pytest.mark.asyncio
async def test_llm_extraction_rejects_garbage_response(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """Мусорный ответ модели — 502, но расход всё равно зафиксирован."""
    headers, model_id = await _setup(client, mock_provider)
    _patch_fetch(monkeypatch)
    mock_provider.spec["POST /chat/completions"] = _chat_handler(
        "не могу помочь", {"prompt_tokens": 100, "completion_tokens": 5}
    )

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "llm", "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 502
    assert "PRICE_IMPORT_LLM_BAD_RESPONSE" in resp.json()["error"]["message"]
    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    # Вызов уже был оплачен провайдеру, поэтому расход нельзя терять.
    assert any(r["units_json"].get("operation") == "price_llm_extract" for r in records)


@pytest.fixture
def pricebot(monkeypatch):
    """Включает/выключает сервис рендера и сбрасывает кэш настроек."""

    def _set(enabled: bool) -> None:
        monkeypatch.setenv("PRICEBOT_ENABLED", "1" if enabled else "0")
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rendered_mode_disabled_is_explained(
    client: AsyncClient, mock_provider, pricebot
) -> None:
    """Выключенный рендер даёт понятную ошибку с именем переменной."""
    headers, _ = await _setup(client, mock_provider)
    pricebot(False)

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "rendered"},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PRICEBOT_ENABLED" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_rendered_mode_uses_render_service(
    client: AsyncClient, mock_provider, monkeypatch, pricebot
) -> None:
    """Режим rendered берёт текст у сервиса рендера и разбирает его."""
    headers, _ = await _setup(client, mock_provider)
    pricebot(True)

    async def fake_render(_url: str, **_kwargs) -> str:
        return "1M OUTPUT TOKENS $0.6\n1M INPUT TOKENS (CACHE MISS) $0.15"

    monkeypatch.setattr("app.api.prices.render_page", fake_render)

    resp = await client.post(
        "/api/v1/prices/extract",
        json={"url": "https://example.com/pricing", "method": "rendered"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "rendered"
    assert body["candidates"]
