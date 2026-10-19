"""Интеграционные тесты CRUD провайдеров и синхронизации моделей.

Проверяют, что ключ не возвращается API, шифруется и что проверка соединения
работает против mock HTTP-сервера. Отдельно покрыт тип `litellm_proxy`
(ADR-0004) — опциональный внешний proxy через тот же OpenAI-совместимый адаптер.
"""
from __future__ import annotations

from decimal import Decimal

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


async def test_sync_models_imports_pricing(client: AsyncClient, mock_provider) -> None:
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}}]}',
    )
    created = await _create_provider(client, headers, base_url=f"http://{host}:{port}")
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/sync-models", headers=headers
    )
    assert resp.status_code == 200
    model_id = resp.json()[0]["id"]

    prices = (
        await client.get(f"/api/v1/prices?model_profile_id={model_id}", headers=headers)
    ).json()
    assert len(prices) == 1
    assert prices[0]["source"] == "api"
    assert prices[0]["currency"] == "USD"
    assert Decimal(prices[0]["input_per_million"]) == Decimal("2.5")
    assert Decimal(prices[0]["output_per_million"]) == Decimal("10")

    # Повторная синхронизация без изменения цены не плодит версии.
    await client.post(f"/api/v1/providers/{created['id']}/sync-models", headers=headers)
    prices = (
        await client.get(f"/api/v1/prices?model_profile_id={model_id}", headers=headers)
    ).json()
    assert len(prices) == 1


async def test_price_accepts_comma_decimal_separator(
    client: AsyncClient, mock_provider
) -> None:
    """Цена с запятой сохраняется: «0,022» из русскоязычной формы.

    Регрессия на реальный дефект: пользователь вводил `0,022`, API отвечал 422
    «Некорректные данные запроса» без указания поля, и сохранить цену было
    невозможно.
    """
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "deepseek-flash", "name": "DeepSeek Flash"}]}',
    )
    created = await _create_provider(client, headers, base_url=f"http://{host}:{port}")
    synced = await client.post(
        f"/api/v1/providers/{created['id']}/sync-models", headers=headers
    )
    model_id = synced.json()[0]["id"]

    resp = await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "0,022",
            "output_per_million": "1,98",
            "currency": "USD",
        },
        headers=headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    # Значение сохранено точно, без потери разрядов: Decimal, а не float.
    assert Decimal(body["input_per_million"]) == Decimal("0.022")
    assert Decimal(body["output_per_million"]) == Decimal("1.98")

    # Каталог сообщает, что цена теперь задана (признак для UI).
    catalog = (await client.get("/api/v1/models", headers=headers)).json()
    assert catalog[0]["has_price"] is True


async def test_validation_error_names_the_field(client: AsyncClient) -> None:
    """Ошибка валидации называет проблемное поле, а не только «некорректные данные».

    Без имени поля пользователь не понимает, что исправить (жалоба при вводе
    цены). Значения из запроса в ответ не эхоируются.
    """
    headers = await _auth(client)
    resp = await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": "00000000-0000-0000-0000-000000000000",
            "input_per_million": "дорого",
            "output_per_million": "1.0",
        },
        headers=headers,
    )

    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "input_per_million" in error["message"]
    assert error["details"]["fields"]


async def test_budget_accepts_comma_decimal_separator(client: AsyncClient) -> None:
    """Лимит бюджета тоже принимает запятую: «5,5» это 5.5."""
    headers = await _auth(client)

    resp = await client.put(
        "/api/v1/budgets",
        json={"daily_limit": "5,5", "monthly_limit": "50,25"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert Decimal(resp.json()["daily_limit"]) == Decimal("5.5")
    assert Decimal(resp.json()["monthly_limit"]) == Decimal("50.25")


async def test_sync_models_does_not_override_manual_price(
    client: AsyncClient, mock_provider
) -> None:
    headers = await _auth(client)
    host, port = mock_provider.server_address
    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "gpt-x", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}}]}',
    )
    created = await _create_provider(client, headers, base_url=f"http://{host}:{port}")
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/sync-models", headers=headers
    )
    model_id = resp.json()[0]["id"]

    # Пользователь задаёт ручную цену (после первичного импорта).
    await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "9.00",
            "output_per_million": "8.00",
            "currency": "USD",
        },
        headers=headers,
    )

    # Синхронизация не перезаписывает ручную цену и не плодит api-версии.
    await client.post(f"/api/v1/providers/{created['id']}/sync-models", headers=headers)
    prices = (
        await client.get(f"/api/v1/prices?model_profile_id={model_id}", headers=headers)
    ).json()
    assert len(prices) == 2
    assert {p["source"] for p in prices} == {"api", "manual"}


async def test_litellm_proxy_provider_uses_openai_compatible_flow(
    client: AsyncClient, mock_provider
) -> None:
    """Тип litellm_proxy проходит обычный OpenAI-совместимый контур (ADR-0004).

    Mock-сервер здесь играет роль локального LiteLLM proxy: отдельный адаптер и
    библиотека litellm не используются, бюджет и цены остаются в Personal AI Hub.
    """
    headers = await _auth(client)
    host, port = mock_provider.server_address

    presets = (await client.get("/api/v1/providers/presets", headers=headers)).json()
    litellm_preset = next(p for p in presets if p["provider_type"] == "litellm_proxy")
    assert litellm_preset["base_url"] == "http://litellm:4000/v1"

    mock_provider.spec["/models"] = (
        200,
        '{"data": [{"id": "litellm-default", "name": "LiteLLM Default"}]}',
    )
    created = await _create_provider(
        client,
        headers,
        provider_type="litellm_proxy",
        display_name="LiteLLM Proxy",
        base_url=f"http://{host}:{port}",
    )
    resp = await client.post(
        f"/api/v1/providers/{created['id']}/sync-models", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()[0]["external_model_id"] == "litellm-default"

    # Каталог моделей и цены ведёт сам Personal AI Hub.
    model_id = resp.json()[0]["id"]
    catalog = (await client.get("/api/v1/models", headers=headers)).json()
    assert [m["id"] for m in catalog] == [model_id]


async def test_litellm_proxy_error_codes_stay_stable(
    client: AsyncClient, mock_provider
) -> None:
    """Ошибки proxy не меняют нормализацию кодов и retryability (ADR-0004).

    Прокси — обычный OpenAI-совместимый endpoint: 401 остаётся
    PROVIDER_UNAUTHORIZED, 429 — PROVIDER_RATE_LIMITED с retryable=True,
    5xx — PROVIDER_ERROR. Иначе появятся новые коды и потеряется retry.
    """
    headers = await _auth(client)
    host, port = mock_provider.server_address
    created = await _create_provider(
        client,
        headers,
        provider_type="litellm_proxy",
        display_name="LiteLLM Proxy",
        base_url=f"http://{host}:{port}",
    )
    provider_id = created["id"]

    for status, expected_ok in ((401, False), (429, False), (503, False)):
        mock_provider.spec["/models"] = (status, '{"error": "upstream"}')
        resp = await client.post(f"/api/v1/providers/{provider_id}/test", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is expected_ok

    # Стабильные коды для HTTP-статусов не зависят от типа провайдера.
    from personal_hub.providers.errors import normalize_http_status

    assert normalize_http_status(401).code == "PROVIDER_UNAUTHORIZED"
    assert normalize_http_status(429).code == "PROVIDER_RATE_LIMITED"
    assert normalize_http_status(429).retryable is True
    assert normalize_http_status(503).code == "PROVIDER_ERROR"
    assert normalize_http_status(503).retryable is True
