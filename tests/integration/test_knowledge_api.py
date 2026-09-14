"""Интеграционные тесты RAG: индексация документа и запрос с цитатами."""
from __future__ import annotations

import json
import uuid

from httpx import AsyncClient

import worker.tasks.ingest  # noqa: F401  # регистрирует обработчик document_ingest
from worker.tasks.jobs import execute_job


def _embedding_handler(method, path, body):
    data = json.loads(body)
    inputs = data["input"] if isinstance(data["input"], list) else [data["input"]]
    embeddings = [{"embedding": [1.0, 0.0, 0.0]} for _ in inputs]
    return 200, json.dumps({"data": embeddings}), {}


async def _bootstrap(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _model_id(client: AsyncClient, headers: dict, mock_provider) -> str:
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        '{"data": [{"id": "embed-1", "name": "Embed"}]}',
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
    catalog = await client.get("/api/v1/models", headers=headers)
    return catalog.json()[0]["id"]


async def test_ingest_and_query(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Docs", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("notes.txt", "Persia was a great empire".encode(), "text/plain")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "ready"

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "Persia", "top_k": 5},
        headers=headers,
    )
    result = query.json()
    assert result["sufficient"] is True
    assert len(result["citations"]) >= 1
    assert "Persia" in result["citations"][0]["text"]
    assert result["citations"][0]["document_title"] == "notes.txt"


async def test_query_empty_kb_insufficient(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Empty", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "anything"},
        headers=headers,
    )
    result = query.json()
    assert result["sufficient"] is False
    assert result["citations"] == []
