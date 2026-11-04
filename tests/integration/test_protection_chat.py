"""Интеграционные тесты гибридного чата (ADR-0007, срез 4).

Проверяют главный риск: в режиме protected_hybrid провайдер получает только
sanitized-текст, ответ восстанавливается локально, а восстановленные значения
не уходят обратно в следующем turn.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from personal_hub.config import get_settings

_TEXT = "Договор с ООО «Ромашка». Почта: ivan.petrov@example.com"


def _sse_body(*chunks: str) -> str:
    """Собирает тело потокового ответа провайдера."""
    return "".join(f"data: {c}\n\n" for c in chunks)


def _capture_sse(store: list[dict], *chunks: str):
    """Обработчик чата: запоминает тело запроса и отдаёт поток."""

    def handler(_method: str, _path: str, body: bytes):
        store.append(json.loads(body))
        text = _sse_body(*chunks)
        return (200, text, {"Content-Type": "text/event-stream"})

    return handler


async def _collect_events(client: AsyncClient, generation_id: str, headers: dict) -> list[dict]:
    """Читает SSE-события генерации до закрытия потока."""
    events: list[dict] = []
    async with client.stream(
        "GET", f"/api/v1/generations/{generation_id}/events", headers=headers
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def _setup(client: AsyncClient, mock_provider) -> tuple[dict[str, str], str, str]:
    """Готовит провайдера, модель с ценой и диалог."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "gpt-x", "name": "GPT X"}]}),
    )
    provider = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "Test",
            "base_url": f"http://{host}:{port}",
            "api_key": "sk-test",
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
        "/api/v1/conversations", json={"title": "Тест"}, headers=headers
    )
    conversation_id = conversation.json()["id"]
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "protected_hybrid"},
        headers=headers,
    )
    return headers, model_id, conversation_id


async def _prepare_and_commit(
    client: AsyncClient, headers: dict, conversation_id: str, text: str
) -> dict:
    """Проходит preview → commit и возвращает результат подготовки."""
    preview = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/prepare",
        json={"text": text, "dictionary": {"org": ["ООО «Ромашка»"]}},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    commit = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json={
            "preparation_id": body["preparation_id"],
            "digest": body["digest"],
            "revision": body["revision"],
        },
        headers=headers,
    )
    assert commit.status_code == 200, commit.text
    return body


@pytest.fixture
def protection_enabled(monkeypatch):
    """Включает защищённые режимы для теста."""
    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hybrid_sends_only_sanitized_context(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Провайдер получает псевдонимы, пользователь — восстановленный ответ."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    captured: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(
        captured,
        '{"choices":[{"delta":{"content":"Пишите на "}}]}',
        '{"choices":[{"delta":{"content":"[EMAIL_1]"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":5}}',
        "[DONE]",
    )
    preparation = await _prepare_and_commit(
        client, headers, conversation_id, _TEXT
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": _TEXT,
            "model_profile_id": model_id,
            "preparation_id": preparation["preparation_id"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    events = await _collect_events(client, resp.json()["generation_id"], headers)

    # Провайдеру не ушло ни одного приватного значения.
    payload = json.dumps(captured[0], ensure_ascii=False)
    assert "ivan.petrov@example.com" not in payload
    assert "Ромашка" not in payload
    assert "[EMAIL_1]" in payload

    # Пользователь видит восстановленный текст.
    text = "".join(e["delta"] for e in events if e["event"] == "content.delta")
    assert "ivan.petrov@example.com" in text
    assert any(e["event"] == "restoration.completed" for e in events)

    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    messages = detail.json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    user = [m for m in messages if m["role"] == "user"][0]
    assert assistant["content"] == text
    # Sanitized-версия сохранена для следующего turn.
    assert "ivan.petrov@example.com" not in assistant["protection"]["sanitized"]
    assert "[EMAIL_1]" in assistant["protection"]["sanitized"]
    assert user["protection"]["sanitized"] == preparation["sanitized_messages"][0]
    # Ревизия выросла: старая подготовка больше не подходит.
    assert detail.json()["protection_revision"] == preparation["revision"] + 1


@pytest.mark.asyncio
async def test_hybrid_requires_preparation(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Без подготовки сообщение не отправляется — иначе утёк бы приватный текст."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    called: list[int] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(called, "[DONE]")

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PROTECTION_PREPARATION_REQUIRED" in resp.json()["error"]["message"]
    assert called == []


@pytest.mark.asyncio
async def test_hybrid_rejects_stale_preparation(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Подготовка после изменения контекста не принимается."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    mock_provider.spec["POST /chat/completions"] = _capture_sse(
        [], '{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"
    )
    preparation = await _prepare_and_commit(client, headers, conversation_id, _TEXT)
    # Смена режима повышает ревизию, подготовка становится устаревшей.
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "cloud_controlled"},
        headers=headers,
    )
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "protected_hybrid"},
        headers=headers,
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": _TEXT,
            "model_profile_id": model_id,
            "preparation_id": preparation["preparation_id"],
        },
        headers=headers,
    )

    assert resp.status_code == 409
    assert "PROTECTION_PREVIEW_STALE" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_hybrid_rejects_changed_content(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Подмена текста после preview отклоняется по digest."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    mock_provider.spec["POST /chat/completions"] = _capture_sse(
        [], '{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"
    )
    preparation = await _prepare_and_commit(client, headers, conversation_id, _TEXT)

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": _TEXT + " и ещё секрет",
            "model_profile_id": model_id,
            "preparation_id": preparation["preparation_id"],
        },
        headers=headers,
    )

    assert resp.status_code == 409
    assert "PROTECTION_DIGEST_MISMATCH" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_cloud_mode_still_sends_private_context(
    client: AsyncClient, mock_provider
) -> None:
    """Облачный режим не меняет прежнее поведение."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "cloud_controlled"},
        headers=headers,
    )
    captured: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(
        captured, '{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 200
    # Генерация выполняется в фоне: дожидаемся её завершения через SSE,
    # иначе провайдер ещё не получил запрос и captured пуст.
    await _collect_events(client, resp.json()["generation_id"], headers)
    payload = json.dumps(captured[0], ensure_ascii=False)
    assert "ivan.petrov@example.com" in payload


@pytest.mark.asyncio
async def test_local_only_blocks_external_call(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Локальный режим не отправляет данные наружу, пока runtime не готов."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "local_only"},
        headers=headers,
    )
    called: list[int] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(called, "[DONE]")

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "локально" in resp.json()["error"]["message"].lower()
    assert called == []
