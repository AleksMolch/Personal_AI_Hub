"""Интеграционные тесты auth-потока: bootstrap, login, me.

Проверяют сценарий первого администратора и авторизации против реальной БД.
"""
from __future__ import annotations

from httpx import AsyncClient


async def _bootstrap(client: AsyncClient, username: str = "admin", password: str = "supersecret") -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": username, "password": password}
    )
    assert resp.status_code == 201
    return resp.json()


async def test_bootstrap_creates_admin_and_token(client: AsyncClient) -> None:
    data = await _bootstrap(client)
    assert data["access_token"]
    assert data["user"]["username"] == "admin"
    assert data["user"]["is_admin"] is True


async def test_bootstrap_second_time_conflict(client: AsyncClient) -> None:
    await _bootstrap(client)
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin2", "password": "anotherpass"}
    )
    assert resp.status_code == 409


async def test_login_success(client: AsyncClient) -> None:
    await _bootstrap(client)
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password(client: AsyncClient) -> None:
    await _bootstrap(client)
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_token(client: AsyncClient) -> None:
    data = await _bootstrap(client)
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"
