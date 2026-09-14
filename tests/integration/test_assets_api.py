"""Интеграционные тесты ассетов: загрузка, скачивание, удаление."""
from __future__ import annotations

import hashlib

from httpx import AsyncClient


async def _bootstrap(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_asset_upload_list_download(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    data = b"hello document"

    resp = await client.post(
        "/api/v1/assets/uploads",
        headers=headers,
        files={"file": ("doc.txt", data, "text/plain")},
        data={"kind": "document"},
    )
    assert resp.status_code == 201
    asset = resp.json()
    assert asset["size_bytes"] == len(data)
    assert asset["sha256"] == hashlib.sha256(data).hexdigest()
    assert asset["mime_type"] == "text/plain"

    listing = (await client.get("/api/v1/assets", headers=headers)).json()
    assert len(listing) == 1

    content = await client.get(f"/api/v1/assets/{asset['id']}/content", headers=headers)
    assert content.status_code == 200
    assert content.content == data


async def test_asset_delete_creates_job(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    resp = await client.post(
        "/api/v1/assets/uploads",
        headers=headers,
        files={"file": ("doc.txt", b"data", "text/plain")},
    )
    asset_id = resp.json()["id"]

    delete = await client.delete(f"/api/v1/assets/{asset_id}", headers=headers)
    assert delete.status_code == 202
    job_id = delete.json()["job_id"]

    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["type"] == "document_delete"
    assert job["status"] == "queued"
