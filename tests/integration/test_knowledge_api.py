"""Интеграционные тесты RAG: индексация документа, запрос с цитатами.

Покрывают: базовый ingest/query, биллинг эмбеддингов и RAG-синтеза (вызовы не
уходят мимо UsageRecord), OCR скан-PDF (детерминированный fake-backend) и
видимую ошибку OCR в статусе документа.
"""
from __future__ import annotations

import io
import json
import uuid

import worker.tasks.ingest  # noqa: F401  # регистрирует обработчик document_ingest
from httpx import AsyncClient
from personal_hub.db.engine import get_session_factory
from personal_hub.models import UsageRecord
from personal_hub.ocr import OcrError, OcrResult
from sqlalchemy import select
from worker.tasks.jobs import execute_job


def _embedding_handler(method, path, body):
    data = json.loads(body)
    inputs = data["input"] if isinstance(data["input"], list) else [data["input"]]
    embeddings = [{"embedding": [1.0, 0.0, 0.0]} for _ in inputs]
    return 200, json.dumps({"data": embeddings}), {}


def _chat_handler(method, path, body):
    return 200, '{"choices":[{"message":{"content":"Ответ на основе фрагментов [1]"}}]}', {}


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


async def _set_price(client: AsyncClient, headers: dict, model_id: str) -> None:
    await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "1.00",
            "output_per_million": "2.00",
            "currency": "USD",
        },
        headers=headers,
    )


async def _usage_operations() -> set[str]:
    """Возвращает множество операций из UsageRecord (units_json["operation"])."""
    factory = get_session_factory()
    async with factory() as session:
        records = (await session.execute(select(UsageRecord))).scalars().all()
        return {r.units_json.get("operation") for r in records if r.units_json}


def _blank_pdf() -> bytes:
    """PDF-«скан» без текстового слоя (пустые страницы)."""
    from pypdf import PdfWriter

    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(buf)
    return buf.getvalue()


class _DeterministicOcr:
    """Fake-OCR для E2E: детерминированный текст без внешнего движка."""

    name = "test-ocr"

    def __init__(self, text: str = "scan only content") -> None:
        self.text = text

    def is_available(self) -> bool:
        return True

    def recognize(self, image, languages: list[str]) -> OcrResult:
        return OcrResult(text=self.text, warnings=[])


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
        files={"file": ("notes.txt", b"Persia was a great empire", "text/plain")},
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


async def test_query_synthesizes_answer(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler
    mock_provider.spec["POST /chat/completions"] = _chat_handler
    await _set_price(client, headers, model_id)

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Docs", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("notes.txt", b"Persia was a great empire", "text/plain")},
    )
    await execute_job(uuid.UUID(resp.json()["job_id"]))

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "Persia", "chat_model_profile_id": model_id},
        headers=headers,
    )
    result = query.json()
    assert result["sufficient"] is True
    assert result["answer"] == "Ответ на основе фрагментов [1]"
    assert len(result["citations"]) >= 1


async def test_synthesis_skipped_without_price(client: AsyncClient, mock_provider) -> None:
    """Без цены платный синтез не вызывается (answer=None)."""
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler
    mock_provider.spec["POST /chat/completions"] = _chat_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Docs", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("notes.txt", b"Persia was a great empire", "text/plain")},
    )
    await execute_job(uuid.UUID(resp.json()["job_id"]))

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "Persia", "chat_model_profile_id": model_id},
        headers=headers,
    )
    result = query.json()
    assert result["sufficient"] is True
    assert result["answer"] is None


async def test_rag_billing_records_usage(
    client: AsyncClient, mock_provider
) -> None:
    """Embedding индексации, embedding запроса и синтез пишут UsageRecord."""
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler
    mock_provider.spec["POST /chat/completions"] = _chat_handler
    await _set_price(client, headers, model_id)

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Docs", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("notes.txt", b"Persia was a great empire", "text/plain")},
    )
    await execute_job(uuid.UUID(resp.json()["job_id"]))

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "Persia", "chat_model_profile_id": model_id},
        headers=headers,
    )
    assert query.json()["answer"] is not None

    ops = await _usage_operations()
    assert {"embedding", "rag_query_embedding", "rag_synthesis"} <= ops


async def test_ocr_scan_document_indexed(client: AsyncClient, mock_provider, monkeypatch) -> None:
    """Скан-PDF (без текстового слоя) OCR-ится и попадает в retrieval."""
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler
    monkeypatch.setattr(
        "personal_hub.ocr.get_ocr_backend", lambda: _DeterministicOcr("scan only content")
    )

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Scans", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("scan.pdf", _blank_pdf(), "application/pdf")},
    )
    assert resp.status_code == 200
    await execute_job(uuid.UUID(resp.json()["job_id"]))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "ready"

    query = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/query",
        json={"text": "scan", "top_k": 5},
        headers=headers,
    )
    result = query.json()
    assert result["sufficient"] is True
    assert any("scan only content" in c["text"] for c in result["citations"])


async def test_ocr_failure_marks_document_failed(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """Ошибка OCR видна: документ failed, job failed (не проглатывается)."""
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    class _BrokenOcr:
        name = "broken-ocr"

        def is_available(self) -> bool:
            return True

        def recognize(self, image, languages: list[str]) -> OcrResult:
            # Ошибка движка должна попадать в статус документа.
            raise OcrError("OCR_FAILED", "движок не смог распознать страницу")

    monkeypatch.setattr("personal_hub.ocr.get_ocr_backend", lambda: _BrokenOcr())

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Scans", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("broken.pdf", _blank_pdf(), "application/pdf")},
    )
    job_id = resp.json()["job_id"]
    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "failed"
    assert document["error_code"] == "OCR_FAILED"

    from personal_hub.db.engine import get_session_factory
    from personal_hub.models import Job

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "failed"
