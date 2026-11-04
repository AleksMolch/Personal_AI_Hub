"""Интеграционные тесты HTTP-контракта защищённых режимов (ADR-0007, срез 3).

Проверяют пользовательский сценарий: включённая защита, переключение режима,
preview с псевдонимами, подтверждение конкретного digest, отказы при изменении
содержимого и устаревшем preview.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from personal_hub.config import get_settings
from personal_hub.db.engine import get_session_factory
from personal_hub.models import Message

_TEXT = "Договор с ООО «Ромашка». Почта: ivan.petrov@example.com"


@pytest.fixture
def protection_enabled(monkeypatch):
    """Включает защищённые режимы и сбрасывает кэш настроек."""
    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Создаёт админа и диалог, возвращает заголовки и id диалога."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Тест"}, headers=headers
    )
    return headers, conversation.json()["id"]


async def _protected(client: AsyncClient, headers: dict[str, str], conversation_id: str) -> None:
    """Переключает диалог в режим защищённого гибрида."""
    resp = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "protected_hybrid"},
        headers=headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_disabled_feature_is_explained(client: AsyncClient, monkeypatch) -> None:
    """Пока флаг выключен, эндпоинты честно отказывают."""
    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "0")
    get_settings.cache_clear()
    headers, conversation_id = await _setup(client)

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/prepare",
        json={"text": _TEXT},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "PROTECTION_MODES_ENABLED" in resp.json()["error"]["message"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_prepare_requires_protected_mode(
    client: AsyncClient, protection_enabled
) -> None:
    """В облачном режиме подготовка не нужна и отклоняется с подсказкой."""
    headers, conversation_id = await _setup(client)

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/prepare",
        json={"text": _TEXT},
        headers=headers,
    )

    assert resp.status_code == 400
    assert "Защищённый гибрид" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_prepare_shows_sanitized_preview(
    client: AsyncClient, protection_enabled
) -> None:
    """Preview содержит псевдонимы вместо данных и digest для commit."""
    headers, conversation_id = await _setup(client)
    await _protected(client, headers, conversation_id)

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/prepare",
        json={"text": _TEXT, "dictionary": {"org": ["ООО «Ромашка»"]}},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    sanitized = "\n".join(body["sanitized_messages"])
    assert "ivan.petrov@example.com" not in sanitized
    assert "Ромашка" not in sanitized
    assert "[EMAIL_1]" in sanitized
    assert "[ORG_1]" in sanitized
    assert len(body["digest"]) == 64
    assert body["revision"] == 1
    # Приватный preview нужен, чтобы пользователь видел разницу.
    assert "ivan.petrov@example.com" in "\n".join(body["private_messages"])
    categories = {entity["category"] for entity in body["entities"]}
    assert {"email", "org"} <= categories


@pytest.mark.asyncio
async def test_commit_returns_sanitized_text_and_is_idempotent(
    client: AsyncClient, protection_enabled
) -> None:
    """Подтверждение отдаёт sanitized-текст; повтор не создаёт второй запрос."""
    headers, conversation_id = await _setup(client)
    await _protected(client, headers, conversation_id)
    preview = (
        await client.post(
            f"/api/v1/protection/conversations/{conversation_id}/prepare",
            json={"text": _TEXT},
            headers=headers,
        )
    ).json()
    body = {
        "preparation_id": preview["preparation_id"],
        "digest": preview["digest"],
        "revision": preview["revision"],
    }

    first = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json=body,
        headers=headers,
    )
    second = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json=body,
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "committed"
    assert "ivan.petrov@example.com" not in first.json()["sanitized_text"]
    assert second.status_code == 200
    assert second.json()["preparation_id"] == first.json()["preparation_id"]


@pytest.mark.asyncio
async def test_commit_rejects_changed_digest(
    client: AsyncClient, protection_enabled
) -> None:
    """Подмена digest отклоняется: отправить другое содержимое нельзя."""
    headers, conversation_id = await _setup(client)
    await _protected(client, headers, conversation_id)
    preview = (
        await client.post(
            f"/api/v1/protection/conversations/{conversation_id}/prepare",
            json={"text": _TEXT},
            headers=headers,
        )
    ).json()

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json={
            "preparation_id": preview["preparation_id"],
            "digest": "0" * 64,
            "revision": preview["revision"],
        },
        headers=headers,
    )

    assert resp.status_code == 409
    assert "PROTECTION_DIGEST_MISMATCH" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_commit_rejects_stale_preview_after_mode_change(
    client: AsyncClient, protection_enabled
) -> None:
    """После смены режима старый preview не может быть отправлен."""
    headers, conversation_id = await _setup(client)
    await _protected(client, headers, conversation_id)
    preview = (
        await client.post(
            f"/api/v1/protection/conversations/{conversation_id}/prepare",
            json={"text": _TEXT},
            headers=headers,
        )
    ).json()
    # Смена режима увеличивает ревизию диалога.
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "local_only"},
        headers=headers,
    )

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json={
            "preparation_id": preview["preparation_id"],
            "digest": preview["digest"],
            "revision": preview["revision"],
        },
        headers=headers,
    )

    assert resp.status_code == 409
    assert "PROTECTION_PREVIEW_STALE" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_foreign_conversation_is_not_found(
    client: AsyncClient, protection_enabled
) -> None:
    """Чужой (или несуществующий) диалог неотличим от отсутствующего."""
    headers, _ = await _setup(client)

    resp = await client.post(
        f"/api/v1/protection/conversations/{uuid.uuid4()}/prepare",
        json={"text": _TEXT},
        headers=headers,
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_history_is_included_and_sanitized(
    client: AsyncClient, protection_enabled
) -> None:
    """История диалога попадает в preview и тоже очищается."""
    headers, conversation_id = await _setup(client)
    await _protected(client, headers, conversation_id)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Message(
                conversation_id=uuid.UUID(conversation_id),
                role="user",
                content="Раньше писали на old@example.com",
            )
        )
        await session.commit()

    resp = await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/prepare",
        json={"text": "Новое сообщение"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sanitized_messages"]) == 2
    assert "old@example.com" not in "\n".join(body["sanitized_messages"])
    assert "old@example.com" in "\n".join(body["private_messages"])
