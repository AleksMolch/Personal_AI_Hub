"""Contract-тесты OpenAI-compatible адаптера через mock HTTP-сервер.

Проверяют health и list_models на зафиксированных сценариях: успех, 401,
429 и список моделей.
"""
from __future__ import annotations

from decimal import Decimal

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


@pytest.mark.asyncio
async def test_list_models_parses_pricing(mock_provider) -> None:
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "pricing": {'
        '"prompt": "0.0000025", "completion": "0.00001", '
        '"cache_read": "0.00000025", "cache_write": "0.0000025"}}]}',
    )
    models = await OpenAICompatibleAdapter().list_models(_connection(mock_provider))
    pricing = models[0].pricing
    assert pricing is not None
    assert pricing.input_per_million == Decimal("2.5")
    assert pricing.output_per_million == Decimal("10")
    assert pricing.cache_read_per_million == Decimal("0.25")
    assert pricing.cache_write_per_million == Decimal("2.5")


@pytest.mark.asyncio
async def test_list_models_without_pricing(mock_provider) -> None:
    mock_provider.spec["/models"] = (200, '{"data": [{"id": "gpt-x"}]}')
    models = await OpenAICompatibleAdapter().list_models(_connection(mock_provider))
    assert models[0].pricing is None


@pytest.mark.asyncio
async def test_list_models_ignores_malformed_pricing(mock_provider) -> None:
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "pricing": {"prompt": "abc", "completion": "0.1"}}]}',
    )
    models = await OpenAICompatibleAdapter().list_models(_connection(mock_provider))
    assert models[0].pricing is None


@pytest.mark.asyncio
async def test_embed_parses_usage(mock_provider) -> None:
    """Usage эмбеддингов не теряется: расход фиксируется как actual."""
    mock_provider.spec["POST /embeddings"] = (
        200,
        '{"data":[{"embedding":[1.0,2.0]}],"usage":{"prompt_tokens":11,"total_tokens":11}}',
    )
    result = await OpenAICompatibleAdapter().embed(
        _connection(mock_provider), ["hello"], "embed-1"
    )
    assert result.vectors == [[1.0, 2.0]]
    assert result.usage == {"prompt_tokens": 11, "total_tokens": 11}
