"""Интеграционные тесты RAG: индексация документа, запрос с цитатами.

Покрывают: базовый ingest/query, биллинг эмбеддингов и RAG-синтеза (вызовы не
уходят мимо UsageRecord), OCR скан-PDF (детерминированный fake-backend),
реальный OCR-путь (poppler→tesseract) на пустой и на читаемой странице и
видимую ошибку OCR в статусе документа.
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
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


def _scanned_pdf(lines: list[str], font_size: int = 48) -> bytes:
    """PDF-«скан» с текстом: страница-картинка БЕЗ текстового слоя.

    Именно такой формат запускает OCR-путь: с текстовым слоем Tesseract не
    вызывается. Шрифт встроенный в Pillow, поэтому фикстура не требует
    системных файлов шрифтов в образе.
    """
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=font_size)
    y = 300
    for line in lines:
        draw.text((150, y), line, fill="black", font=font)
        y += int(font_size * 2.2)
    buf = io.BytesIO()
    image.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


def _normalized_ocr(text: str) -> str:
    """OCR-текст без пробелов/пунктуации и в верхнем регистре.

    Нужно для устойчивых проверок: Tesseract путает I/l и часто вставляет
    переводы строк, поэтому сравнивать «как есть» нельзя.
    """
    return "".join(ch for ch in text.upper() if ch.isalnum())


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


async def test_real_tesseract_blank_scan_path(
    client: AsyncClient, mock_provider
) -> None:
    """Реальный OCR-путь (pdf2image+poppler→tesseract) работает без сбоев.

    Пустой PDF-«скан» с реальным Tesseract не даёт текста → документ failed с
    EMPTY_DOCUMENT. Тест доказывает, что реальные бинарники (tesseract,
    poppler) и pytesseract в составе образа корректно связаны и не требуют
    mock-backend.
    """
    import shutil

    if shutil.which("tesseract") is None or shutil.which("pdftoppm") is None:
        pytest.skip("tesseract/poppler недоступны (unit-контейнер)")

    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Scans", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("blank.pdf", _blank_pdf(), "application/pdf")},
    )
    job_id = resp.json()["job_id"]
    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "failed"
    assert document["error_code"] == "EMPTY_DOCUMENT"

    from personal_hub.db.engine import get_session_factory
    from personal_hub.models import Job

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "failed"


async def test_real_tesseract_extracts_text_from_scan(
    client: AsyncClient, mock_provider
) -> None:
    """Реальный OCR читает текст скана, и текст попадает в индекс.

    Закрывает прошлый пробел: тест пути проверял только связку бинарников на
    пустой странице (EMPTY_DOCUMENT), но не качество распознавания. Теперь
    фикстура — PDF из картинки с читаемым текстом без текстового слоя, и путь
    poppler → Tesseract → чанки проверяется по содержимому индекса.
    """
    import shutil

    if shutil.which("tesseract") is None or shutil.which("pdftoppm") is None:
        pytest.skip("tesseract/poppler недоступны (unit-контейнер)")

    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Scans", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={
            "file": (
                "scan.pdf",
                _scanned_pdf(["VECTORSEARCH", "PERSONAL AI HUB", "STAGE ONE 2026"]),
                "application/pdf",
            )
        },
    )
    job_id = resp.json()["job_id"]
    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "ready"

    from personal_hub.models import Chunk

    factory = get_session_factory()
    async with factory() as session:
        chunks = (await session.execute(select(Chunk))).scalars().all()
    # VECTORSEARCH выбран как различимый токен (без неоднозначных I/l в «AI»).
    assert any("VECTORSEARCH" in _normalized_ocr(chunk.content) for chunk in chunks)


async def test_ingest_embedding_failure_marks_document_failed(
    client: AsyncClient, mock_provider
) -> None:
    """Сбой эмбеддингов виден в статусе документа, а не оставляет его pending.

    Провайдер отвечает 500 — индексация падает, документ должен получить
    status=failed и нормализованный код ошибки, а резервирование бюджета
    (если было) — освободиться.
    """
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    await _set_price(client, headers, model_id)
    mock_provider.spec["POST /embeddings"] = (500, '{"error": "upstream boom"}')

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Broken", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("notes.txt", b"Persia was a great empire", "text/plain")},
    )
    job_id = resp.json()["job_id"]
    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "failed"
    assert document["error_code"] == "PROVIDER_ERROR"

    from personal_hub.models import CostReservation, Job, ReservationStatus

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "failed"
        reservations = (await session.execute(select(CostReservation))).scalars().all()
    # Резерв бюджета не должен остаться активным после падения индексации.
    assert reservations
    assert all(r.status == ReservationStatus.CANCELLED.value for r in reservations)


async def test_ingest_corrupt_image_marks_document_failed(
    client: AsyncClient, mock_provider
) -> None:
    """Битый файл изображения даёт failed с кодом, а не вечный pending.

    Изображения принимаются как документы (OCR-ветка), поэтому ошибка разбора
    (не-PNG содержимое под видом PNG) должна быть видна так же, как ошибка OCR.
    """
    headers = await _bootstrap(client)
    model_id = await _model_id(client, headers, mock_provider)
    mock_provider.spec["POST /embeddings"] = _embedding_handler

    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Broken", "embedding_model_profile_id": model_id},
        headers=headers,
    )
    kb_id = kb.json()["id"]

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("photo.png", b"this is not a png", "image/png")},
    )
    job_id = resp.json()["job_id"]
    await execute_job(uuid.UUID(job_id))

    detail = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    document = detail.json()["documents"][0]
    assert document["status"] == "failed"
    assert document["error_code"] == "PARSE_FAILED"
