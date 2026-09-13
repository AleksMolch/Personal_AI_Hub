"""Contract-тесты потокового чата (SSE-парсинг OpenAI-compatible).

Проверяют разбор content.delta, usage, [DONE], а также ошибки.
"""
from __future__ import annotations

import pytest

from personal_hub.providers.base import ChatMessage, ChatRequest, ProviderConnection
from personal_hub.providers.errors import ProviderError
from personal_hub.providers.openai_compatible import OpenAICompatibleAdapter


def _connection(mock_provider) -> ProviderConnection:
    host, port = mock_provider.server_address
    return ProviderConnection(
        provider_type="openai_compatible",
        base_url=f"http://{host}:{port}",
        api_key="sk-test",
    )


def _request() -> ChatRequest:
    return ChatRequest(
        model="gpt-x",
        messages=[ChatMessage(role="user", content="Привет")],
    )


def _sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


@pytest.mark.asyncio
async def test_stream_chat_deltas(mock_provider) -> None:
    body = _sse(
        '{"choices":[{"delta":{"content":"При"}}]}',
        '{"choices":[{"delta":{"content":"вет"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":5}}',
        "[DONE]",
    )
    mock_provider.spec["POST /chat/completions"] = (
        200,
        body,
        {"Content-Type": "text/event-stream"},
    )

    adapter = OpenAICompatibleAdapter()
    chunks = []
    usage = None
    async for chunk in adapter.stream_chat(_connection(mock_provider), _request()):
        chunks.append(chunk.content_delta)
        if chunk.usage:
            usage = chunk.usage

    assert "".join(chunks) == "Привет"
    assert usage == {"total_tokens": 5}


@pytest.mark.asyncio
async def test_stream_chat_unauthorized(mock_provider) -> None:
    mock_provider.spec["POST /chat/completions"] = (401, '{"error": "bad key"}')
    adapter = OpenAICompatibleAdapter()
    with pytest.raises(ProviderError) as exc_info:
        async for _ in adapter.stream_chat(_connection(mock_provider), _request()):
            pass
    assert exc_info.value.code == "PROVIDER_UNAUTHORIZED"


@pytest.mark.asyncio
async def test_stream_chat_malformed_event_skipped(mock_provider) -> None:
    body = _sse(
        "not-json",
        '{"choices":[{"delta":{"content":"ok"}}]}',
        "[DONE]",
    )
    mock_provider.spec["POST /chat/completions"] = (
        200,
        body,
        {"Content-Type": "text/event-stream"},
    )
    adapter = OpenAICompatibleAdapter()
    result = []
    async for chunk in adapter.stream_chat(_connection(mock_provider), _request()):
        result.append(chunk.content_delta)
    assert "".join(result) == "ok"
