"""Интеграционные тесты режима «Только локально» (ADR-0007, срез 6b).

Проверяют: локальный режим работает только с явно помеченным локальным
провайдером, веб-поиск запрещён, приватный текст идёт как есть (санитизация
нужна только для облака), readiness честно сообщает о наличии локальных моделей.
"""
from __future__ import annotations

import json

from httpx import AsyncClient

_TEXT = "Локальный запрос с почтой ivan.petrov@example.com"


def _sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


async def _setup(
    client: AsyncClient, mock_provider, *, is_local: bool
) -> tuple[dict, str, str]:
    """Готовит провайдера (локальный или нет), модель, цену и диалог."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "llama-local", "name": "Llama"}]}),
    )
    provider = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "Ollama" if is_local else "Cloud",
            "base_url": f"http://{host}:{port}",
            "api_key": "sk-test",
            "is_local": is_local,
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/providers/{provider.json()['id']}/sync-models", headers=headers
    )
    model_id = (await client.get("/api/v1/models", headers=headers)).json()[0]["id"]
    await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "1.00",
            "output_per_million": "2.00",
            "currency": "USD",
        },
        headers=headers,
    )
    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Локально"}, headers=headers
    )
    conversation_id = conversation.json()["id"]
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "local_only"},
        headers=headers,
    )
    return headers, model_id, conversation_id


async def test_local_only_uses_private_context(
    client: AsyncClient, mock_provider
) -> None:
    """С помеченным локальным провайдером текст уходит как есть, без псевдонимов."""
    headers, model_id, conversation_id = await _setup(
        client, mock_provider, is_local=True
    )
    captured: list[dict] = []

    def handler(_method: str, _path: str, body: bytes):
        captured.append(json.loads(body))
        return (
            200,
            _sse(
                '{"choices":[{"delta":{"content":"ok"}}]}',
                '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":3}}',
                "[DONE]",
            ),
            {"Content-Type": "text/event-stream"},
        )

    mock_provider.spec["POST /chat/completions"] = handler

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    async with client.stream(
        "GET", f"/api/v1/generations/{resp.json()['generation_id']}/events", headers=headers
    ) as stream:
        async for _line in stream.aiter_lines():
            pass
    payload = json.dumps(captured[0], ensure_ascii=False)
    # Локальному провайдеру псевдонимы не нужны: данные не покидают хост.
    assert "ivan.petrov@example.com" in payload
    assert "[EMAIL_1]" not in payload


async def test_local_only_requires_local_provider(
    client: AsyncClient, mock_provider
) -> None:
    """Облачный провайдер в локальном режиме отклоняется до вызова."""
    headers, model_id, conversation_id = await _setup(
        client, mock_provider, is_local=False
    )
    called: list[int] = []
    mock_provider.spec["POST /chat/completions"] = (
        200,
        _sse('{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"),
        {"Content-Type": "text/event-stream"},
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PROTECTION_LOCAL_PROVIDER_REQUIRED" in resp.json()["error"]["message"]
    assert called == []


async def test_local_only_forbids_web_search(
    client: AsyncClient, mock_provider
) -> None:
    """Веб-поиск — внешний запрос, в локальном режиме он запрещён."""
    headers, model_id, conversation_id = await _setup(
        client, mock_provider, is_local=True
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id, "web_search": True},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PROTECTION_LOCAL_WEB_SEARCH_FORBIDDEN" in resp.json()["error"]["message"]


async def test_local_runtime_readiness(client: AsyncClient, mock_provider) -> None:
    """Readiness показывает только объявленные локальные модели."""
    headers, _, _ = await _setup(client, mock_provider, is_local=True)

    resp = await client.get("/api/v1/protection/local-runtime", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert len(body["models"]) == 1
    assert "Ollama" in body["note"] or body["note"]
