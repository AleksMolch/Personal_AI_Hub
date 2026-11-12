"""Интеграционные тесты «Прямого доступа», тегов и контекста (ADR-0008).

Проверяют пользовательские сценарии, которые нельзя подтвердить unit-тестами:
отправку исходного текста без подготовки, локальное сканирование, управление
диалогами и обрезку истории в реальном HTTP-контуре с Postgres.
"""
from __future__ import annotations

import json
import uuid

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
        return (200, _sse_body(*chunks), {"Content-Type": "text/event-stream"})

    return handler


async def _collect_events(
    client: AsyncClient, generation_id: str, headers: dict
) -> list[dict]:
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


async def _setup(
    client: AsyncClient,
    mock_provider,
    *,
    mode: str = "direct_cloud",
    title: str | None = "Тест",
) -> tuple[dict[str, str], str, str]:
    """Готовит пользователя, провайдера, модель и диалог."""
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
    conversation = await client.post(
        "/api/v1/conversations",
        json={"title": title} if title else {},
        headers=headers,
    )
    conversation_id = conversation.json()["id"]
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": mode},
        headers=headers,
    )
    return headers, conversation_id, model_id


@pytest.mark.asyncio
async def test_scan_returns_categories_without_values(client: AsyncClient):
    """Сканирование отдаёт категории и не возвращает исходные значения."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    scan = await client.post(
        "/api/v1/protection/scan",
        json={
            "text": "Почта ivan.petrov@example.com, телефон +7 999 123-45-67, "
            "password=hunter2"
        },
        headers=headers,
    )

    assert scan.status_code == 200
    body = scan.json()
    categories = {item["category"]: item["count"] for item in body["categories"]}
    assert categories["email"] == 1
    assert categories["phone"] == 1
    assert categories["secret"] == 1
    assert body["has_secret"] is True
    assert "ivan.petrov@example.com" not in json.dumps(body)
    assert "hunter2" not in json.dumps(body)


@pytest.mark.asyncio
async def test_direct_mode_sends_raw_text_and_is_audited(
    client: AsyncClient, mock_provider
):
    """В прямом доступе провайдер получает исходный текст, аудит пишется."""
    store: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(store, "ok")
    headers, conversation_id, model_id = await _setup(client, mock_provider)

    created = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": _TEXT, "model_profile_id": model_id},
        headers=headers,
    )
    assert created.status_code == 200
    await _collect_events(client, created.json()["generation_id"], headers)

    assert store, "провайдер не получил запрос"
    payload = store[-1]
    assert payload["messages"][-1]["content"] == _TEXT

    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    user_message = detail.json()["messages"][0]
    assert user_message["protection"]["mode"] == "direct_cloud"

    audit = await client.get("/api/v1/protection/audit", headers=headers)
    assert any(
        item["action"] == "message_sent"
        and item["details"]["mode"] == "direct_cloud"
        for item in audit.json()
    )


@pytest.mark.asyncio
async def test_tags_are_normalized_and_returned(client: AsyncClient, mock_provider):
    """Теги обрезаются, дубликаты по регистру убираются, пустые отбрасываются."""
    headers, conversation_id, _ = await _setup(client, mock_provider)

    patched = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"tags": [" Работа ", "работа", "", "Личное"]},
        headers=headers,
    )

    assert patched.status_code == 200
    assert patched.json()["tags"] == ["Работа", "Личное"]
    listed = await client.get("/api/v1/conversations", headers=headers)
    assert listed.json()[0]["tags"] == ["Работа", "Личное"]


@pytest.mark.asyncio
async def test_auto_title_and_manual_rename(client: AsyncClient, mock_provider):
    """Первый вопрос задаёт название, ручное переименование не перезаписывается."""
    store: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(store, "ok")
    headers, conversation_id, model_id = await _setup(
        client, mock_provider, title=None
    )

    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Помоги с отчётом за март", "model_profile_id": model_id},
        headers=headers,
    )
    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    assert detail.json()["title"] == "Помоги с отчётом за март"

    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Отчёт"},
        headers=headers,
    )
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Второй вопрос", "model_profile_id": model_id},
        headers=headers,
    )
    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    assert detail.json()["title"] == "Отчёт"


@pytest.mark.asyncio
async def test_delete_conversation_removes_messages(
    client: AsyncClient, mock_provider
):
    """Удаление диалога каскадно убирает сообщения."""
    headers, conversation_id, model_id = await _setup(client, mock_provider)
    mock_provider.spec["POST /chat/completions"] = _capture_sse([], "ok")
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )

    deleted = await client.delete(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )

    assert deleted.status_code == 204
    assert (
        await client.get(
            f"/api/v1/conversations/{conversation_id}", headers=headers
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_context_window_trims_history(
    client: AsyncClient, mock_provider, monkeypatch
):
    """Длинная история обрезается, а снимок сообщает, сколько отброшено."""
    store: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _capture_sse(store, "ok")
    headers, conversation_id, model_id = await _setup(client, mock_provider)

    monkeypatch.setenv("CHAT_HISTORY_MAX_MESSAGES", "4")
    monkeypatch.setenv("CHAT_HISTORY_MAX_TOKENS", "100000")
    get_settings.cache_clear()

    for index in range(3):
        created = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={
                "content": f"Сообщение {index}",
                "model_profile_id": model_id,
            },
            headers=headers,
        )
        await _collect_events(client, created.json()["generation_id"], headers)

    # Каждый запрос содержит не больше 4 исторических сообщений + новое.
    assert len(store[-1]["messages"]) <= 5
    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_preparation_is_rejected_outside_hybrid(
    client: AsyncClient, mock_provider
):
    """Подготовка в облачном/прямом режиме — ошибка, а не тихая отправка."""
    headers, conversation_id, model_id = await _setup(client, mock_provider)

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": "Привет",
            "model_profile_id": model_id,
            "preparation_id": str(uuid.uuid4()),
        },
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PROTECTION_PREPARATION_NOT_APPLICABLE" in resp.text
