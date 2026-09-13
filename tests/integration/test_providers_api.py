"""Интеграционные тесты CRUD провайдеров и синхронизации моделей.

Проверяют, что ключ не возвращается API, шифруется и что проверка соединения
работает против mock HTTP-сервера.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _auth(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_provider(client: AsyncClient, headers: dict, **overrides) -> dict:
    payload = {
        "provider_type": "openai_compatible",
        "display_name": "Test Provider",
        "base_url": "https://example.com/v1",
        "api_key": "sk-secret-key-123456",
        "currency": "USD",
    }
    payload.update(overrides)
    resp = await client.post("/api/v1/providers", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_provider_crud_flow(client: AsyncClient) -> None:
    headers = await _auth(client)
    created = await _create_provider(client, headers)

    # Ключ не возвращается, есть только маска.
    assert "api_key" not in created
    assert "encrypted_secret" not in created
    assert created["key_mask"].endswith("3456")

    # Список.
    listed = (await client.get("/api/v1/providers", headers=headers)).json()
    assert len(listed) == 1
    assert listed[0]["key_mask"].endswith("3456")

    # Обновление ключа и имени.
    resp = await client.patch(
        f"/api/v1/providers/{created['id']}",
        json={"display_name": "Renamed", "api_key": "sk-new-key-9999"},
        headers=headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["display_name"] == "Renamed"
    assert updated["key_mask"].endswith("9999")

    # Удаление.
    resp = await client.delete(f"/api/v1/providers/{created['id']}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get("/api/v1/providers", headers=headers)).json() == []


async def test_provider_create_invalid_type(client: AsyncClient) -> None:
    headers = await _auth(client)
    resp = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "unknown_type",
            "display_name": "X",
            "base_url": "https://example.com/v1",
            "api_key": "sk-key",
        },
        headers=headers,
    )
    assert resp.status_code == 422


async def test_provider_create_invalid_base_url(client: AsyncClient) -> None:
    headers = await _auth(client)
    resp = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "X",
            "base_url": "ftp://example.com",
            "api_key": "sk-key",
        },
        headers=headers,
    )
    assert resp.status_code == 422


async def test_provider_test_connection_ok(client: AsyncClient, mock_provider) -> None:
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (200, '{"data": [{"id": "m1"}]}')
    created = await _create_provider(
        client, headers, base_url=f"http://{host}:{port}"
    )
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/test", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["model_count"] == 1


async def test_provider_test_connection_unauthorized(client: AsyncClient, mock_provider) -> None:
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (401, '{"error": "bad key"}')
    created = await _create_provider(
        client, headers, base_url=f"http://{host}:{port}"
    )
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/test", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


async def test_sync_models(client: AsyncClient, mock_provider) -> None:
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "name": "GPT X", "context_length": 8192}]}',
    )
    created = await _create_provider(client, headers, base_url=f"http://{host}:{port}")
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/sync-models", headers=headers
    )
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) == 1
    assert models[0]["external_model_id"] == "gpt-x"

    # Модели видны в каталоге.
    catalog = await client.get("/api/v1/models", headers=headers)
    assert catalog.status_code == 200
    assert len(catalog.json()) == 1
