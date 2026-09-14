"""Интеграционные тесты табличного анализа через API."""
from __future__ import annotations

from httpx import AsyncClient


async def _bootstrap(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _upload_csv(client: AsyncClient, headers: dict) -> str:
    data = b"name,value\na,10\nb,20\nc,30\n"
    resp = await client.post(
        "/api/v1/assets/uploads",
        headers=headers,
        files={"file": ("data.csv", data, "text/csv")},
    )
    return resp.json()["id"]


async def test_table_preview(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    asset_id = await _upload_csv(client, headers)

    resp = await client.get(f"/api/v1/assets/{asset_id}/table", headers=headers)
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["format"] == "csv"
    assert [c["name"] for c in preview["columns"]] == ["name", "value"]
    assert preview["row_count"] == 3


async def test_table_query(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    asset_id = await _upload_csv(client, headers)

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/table/query",
        json={"sql": "SELECT sum(value) AS total FROM data"},
        headers=headers,
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["columns"] == ["total"]
    assert result["rows"] == [[60]]


async def test_table_query_rejects_forbidden_sql(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    asset_id = await _upload_csv(client, headers)

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/table/query",
        json={"sql": "DROP TABLE data"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "HTTP_400"


async def test_table_export_csv(client: AsyncClient) -> None:
    headers = await _bootstrap(client)
    asset_id = await _upload_csv(client, headers)

    resp = await client.post(
        f"/api/v1/assets/{asset_id}/table/export",
        json={"sql": "SELECT * FROM data", "format": "csv"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "name,value" in resp.text
