"""Интеграционные тесты валютных курсов (FxRate)."""
from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient


async def _bootstrap(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_fx_rate_create_and_list(client: AsyncClient) -> None:
    headers = await _bootstrap(client)

    resp = await client.post(
        "/api/v1/fx-rates",
        json={"from_currency": "RUB", "to_currency": "USD", "rate": "0.011"},
        headers=headers,
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["from_currency"] == "RUB"
    assert created["to_currency"] == "USD"
    assert Decimal(created["rate"]) == Decimal("0.011")

    listing = (await client.get("/api/v1/fx-rates", headers=headers)).json()
    assert len(listing) >= 1
    assert listing[0]["from_currency"] == "RUB"


async def test_fx_rate_invalid_rate(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    resp = await client.post(
        "/api/v1/fx-rates",
        json={"from_currency": "RUB", "to_currency": "USD", "rate": "0"},
        headers=headers,
    )
    assert resp.status_code == 422
