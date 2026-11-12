"""Интеграционные тесты библиотеки промптов (ADR-0009)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_prompt_template_crud(client: AsyncClient):
    """Создание, список, изменение и удаление шаблона промпта."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    created = await client.post(
        "/api/v1/prompts",
        json={"title": "Шаблон", "content": "Текст шаблона"},
        headers=headers,
    )
    assert created.status_code == 201
    template_id = created.json()["id"]

    listed = await client.get("/api/v1/prompts", headers=headers)
    assert any(t["id"] == template_id for t in listed.json())

    patched = await client.patch(
        f"/api/v1/prompts/{template_id}",
        json={"title": "Переименован"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Переименован"

    deleted = await client.delete(f"/api/v1/prompts/{template_id}", headers=headers)
    assert deleted.status_code == 204

    listed_after = await client.get("/api/v1/prompts", headers=headers)
    assert all(t["id"] != template_id for t in listed_after.json())


@pytest.mark.asyncio
async def test_prompt_validation(client: AsyncClient):
    """Пустое название или текст отклоняются (422)."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    invalid = await client.post(
        "/api/v1/prompts", json={"title": "", "content": ""}, headers=headers
    )
    assert invalid.status_code == 422
