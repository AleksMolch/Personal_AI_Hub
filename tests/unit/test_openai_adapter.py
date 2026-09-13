"""Contract-тесты OpenAI-compatible адаптера через mock HTTP-сервер.

Проверяют health и list_models на зафиксированных сценариях: успех, 401,
429 и список моделей.
"""
from __future__ import annotations

import pytest

from personal_hub.providers.base import ProviderConnection
from personal_hub.providers.errors import ProviderError
from personal_hub.providers.openai_compatible import OpenAICompatibleAdapter


def _connection(mock_provider) -> ProviderConnection:
    host, port = mock_provider.server_address
    return ProviderConnection(
        provider_type="openai_compatible",
        base_url=f"http://{host}:{port}",
        api_key="sk-test",
    )


@pytest.mark.asyncio
async def test_health_ok(mock_provider) -> None:
    mock_provider.spec["/models"] = (200, '{"data": [{"id": "m1"}, {"id": "m2"}]}')
    result = await OpenAICompatibleAdapter().health(_connection(mock_provider))
    assert result.ok is True
    assert result.model_count == 2


@pytest.mark.asyncio
async def test_health_unauthorized(mock_provider) -> None:
    mock_provider.spec["/models"] = (401, '{"error": "bad key"}')
    result = await OpenAICompatibleAdapter().health(_connection(mock_provider))
    assert result.ok is False
    assert "401" in result.message


@pytest.mark.asyncio
async def test_health_rate_limited(mock_provider) -> None:
    mock_provider.spec["/models"] = (429, '{"error": "slow down"}')
    result = await OpenAICompatibleAdapter().health(_connection(mock_provider))
    assert result.ok is False


@pytest.mark.asyncio
async def test_list_models(mock_provider) -> None:
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "name": "GPT X", "context_length": 8192}]}',
    )
    models = await OpenAICompatibleAdapter().list_models(_connection(mock_provider))
    assert len(models) == 1
    assert models[0].external_id == "gpt-x"
    assert models[0].context_limit == 8192
    assert "chat" in models[0].capabilities


@pytest.mark.asyncio
async def test_list_models_unauthorized_raises(mock_provider) -> None:
    mock_provider.spec["/models"] = (401, '{"error": "bad key"}')
    with pytest.raises(ProviderError) as exc_info:
        await OpenAICompatibleAdapter().list_models(_connection(mock_provider))
    assert exc_info.value.code == "PROVIDER_UNAUTHORIZED"
