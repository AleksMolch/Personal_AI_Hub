"""Обработчики задач индексации документов и удаления.

document_ingest: parse -> chunk -> embed -> Qdrant + Chunk rows.
document_delete: удаление ассета и/или чанков+векторов документа.
Эмбеддинги проходят через бюджетный контур (при наличии цены модели), чтобы
расходы на индексацию не уходили мимо UsageRecord.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.billing import (
    cancel_external_call,
    embedding_units,
    get_latest_price,
    reserve_external_call,
    settle_external_call,
)
from personal_hub.blobstore import get_blob_store
from personal_hub.chunking import chunk_document
from personal_hub.db.engine import get_session_factory
from personal_hub.jobs import JobCancelledError, JobType
from personal_hub.knowledge import collection_name
from personal_hub.models import (
    Asset,
    Chunk,
    Document,
    Job,
    KnowledgeBase,
    ModelProfile,
    PriceSnapshot,
    ProviderCredential,
)
from personal_hub.parsing import parse_document
from personal_hub.providers.base import ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.vectorstore import VectorPoint, get_vector_store
from sqlalchemy import select

from worker.tasks.jobs import register_handler

logger = logging.getLogger("worker.ingest")

EMBED_BATCH_SIZE = 32


async def _check_cancelled(job_id: uuid.UUID) -> None:
    """Проверяет флаг отмены задачи; бросает JobCancelledError при отмене."""
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is not None and job.cancel_requested:
            raise JobCancelledError()


async def _embedding_connection(session, kb: KnowledgeBase):
    """Строит соединение к провайдеру эмбеддингов из профиля KB."""
    if kb.embedding_model_profile_id is None:
        raise ValueError("у базы знаний не задана модель эмбеддингов")
    model = await session.get(ModelProfile, kb.embedding_model_profile_id)
    if model is None:
        raise ValueError("модель эмбеддингов не найдена")
    provider = await session.get(ProviderCredential, model.provider_id)
    if provider is None:
        raise ValueError("провайдер эмбеддингов не найден")
    return (
        ProviderConnection(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=get_cipher().decrypt(provider.encrypted_secret),
        ),
        model,
    )


async def _set_document_status(document_id: uuid.UUID, status: str, error_code: str | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.status = status
            document.error_code = error_code
            await session.commit()


async def ingest_document(job_id: uuid.UUID) -> dict:
    """Индексирует документ: parse -> chunk -> embed -> Qdrant + Chunk rows.

    Parse выполняется в отдельном потоке, чтобы не блокировать event loop
    worker'а при рендере/OCR. Распознавание текста, chunking и запись в
    хранилища идут в основном потоке Celery (async). Ошибки разбора и OCR
    возвращают видимый error_code в статус документа (PARSE_FAILED — для
    битых файлов без собственного кода).
    """
    factory = get_session_factory()
    user_id: uuid.UUID
    provider_id: uuid.UUID
    model_profile_id: uuid.UUID
    embedding_model: str
    collection: str
    price: PriceSnapshot | None

    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}
        document_id = uuid.UUID(job.input_json["document_id"])
        document = await session.get(Document, document_id)
        if document is None:
            return {"error": "document not found"}
        kb = await session.get(KnowledgeBase, document.knowledge_base_id)
        if kb is None:
            return {"error": "knowledge base not found"}
        asset = await session.get(Asset, document.asset_id)
        if asset is None:
            return {"error": "asset not found"}
        connection, model = await _embedding_connection(session, kb)
        price = await get_latest_price(session, model.id)
        asset_key = asset.blob_key
        asset_filename = asset.original_name
        asset_mime = asset.mime_type
        collection = collection_name(kb.id, kb.embedding_version)
        embedding_model = model.external_model_id
        user_id = job.user_id
        provider_id = model.provider_id
        model_profile_id = model.id

    try:
        store = get_blob_store()
        data = b"".join([c async for c in store.open(asset_key)])
        # parse_document — синхронная функция; вызываем через to_thread, чтобы
        # не блокировать event loop при pdf2image/OCR на тяжёлых документах.
        pages = await asyncio.to_thread(parse_document, asset_filename, asset_mime, data)
    except Exception as exc:
        # UnsupportedFormatError/OcrError несут готовый code; битый файл
        # (UnidentifiedImageError, PdfReadError) сводим к PARSE_FAILED, чтобы
        # документ не оставался навсегда в status=pending.
        await _set_document_status(
            document_id, "failed", getattr(exc, "code", None) or "PARSE_FAILED"
        )
        raise

    chunks = chunk_document(pages)
    if not chunks:
        await _set_document_status(document_id, "failed", "EMPTY_DOCUMENT")
        raise ValueError("документ не содержит текста")

    await _check_cancelled(job_id)

    # Резервирование стоимости эмбеддингов ДО вызова провайдера. Цена
    # обязательна: без неё платный вызов не контролируется бюджетом и не
    # выполняется вовсе (симметрично чату и RAG-синтезу).
    billing = None
    if price is None:
        await _set_document_status(document_id, "failed", "PRICE_REQUIRED")
        raise ValueError("цена модели эмбеддингов не задана")
    units = embedding_units("\n".join(c.text for c in chunks), "embedding")
    try:
        async with factory() as session:
            billing = await reserve_external_call(
                session, user_id, price=price, units=units
            )
    except Exception as exc:
        # BUDGET_EXCEEDED/FX_RATE_MISSING и прочие сбои резервирования видны
        # в статусе документа, а не оставляют его в pending.
        await _set_document_status(
            document_id, "failed", getattr(exc, "code", None) or "INGEST_FAILED"
        )
        raise

    usage_totals: dict[str, int] = {}
    embedded_chunks = 0
    try:
        adapter = get_adapter(connection.provider_type)
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            await _check_cancelled(job_id)
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            result = await adapter.embed(connection, [c.text for c in batch], embedding_model)
            vectors.extend(result.vectors)
            embedded_chunks += len(batch)
            # Суммируем фактический usage по батчам (если провайдер его отдал).
            if result.usage:
                usage_totals["prompt_tokens"] = usage_totals.get("prompt_tokens", 0) + int(
                    result.usage.get("prompt_tokens") or 0
                )
                usage_totals["completion_tokens"] = usage_totals.get(
                    "completion_tokens", 0
                ) + int(result.usage.get("completion_tokens") or 0)

        vector_store = get_vector_store()
        await vector_store.ensure_collection(collection, len(vectors[0]))

        points: list[VectorPoint] = []
        chunk_rows: list[Chunk] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk_id = uuid.uuid4()
            vector_id = str(chunk_id)
            points.append(
                VectorPoint(
                    id=vector_id,
                    vector=vector,
                    payload={
                        "document_id": str(document_id),
                        "kb_id": str(kb.id),
                        "page": chunk.page,
                        "position": chunk.position,
                    },
                )
            )
            chunk_rows.append(
                Chunk(
                    document_id=document_id,
                    content=chunk.text,
                    position=chunk.position,
                    page=chunk.page,
                    checksum=chunk.checksum,
                    vector_id=vector_id,
                )
            )

        await vector_store.upsert(collection, points)

        async with factory() as session:
            session.add_all(chunk_rows)
            document = await session.get(Document, document_id)
            if document is not None:
                document.status = "ready"
            await session.commit()
    except Exception as exc:
        if billing is not None:
            if embedded_chunks:
                # Провайдер уже выполнил (и списал) часть работы: резерв
                # финализируем, а не отменяем. Если usage не отдан — считаем
                # оценку только по фактически обработанным чанкам.
                partial_units = embedding_units(
                    "\n".join(c.text for c in chunks[:embedded_chunks]), "embedding"
                )
                async with factory() as session:
                    await settle_external_call(
                        session,
                        user_id=user_id,
                        provider_id=provider_id,
                        model_profile_id=model_profile_id,
                        billing=billing,
                        usage=usage_totals or None,
                        estimated_units=partial_units if not usage_totals else None,
                    )
            else:
                async with factory() as session:
                    await cancel_external_call(session, billing=billing)
        # Причина видна пользователю: документ не должен «зависать» в pending
        # при сбое провайдера (код из ProviderError) или другом сбое записи.
        # Отмена — отдельный сценарий: статус не меняем, задачу можно перезапустить.
        if not isinstance(exc, JobCancelledError):
            await _set_document_status(
                document_id, "failed", getattr(exc, "code", None) or "INGEST_FAILED"
            )
        raise

    if billing is not None:
        async with factory() as session:
            await settle_external_call(
                session,
                user_id=user_id,
                provider_id=provider_id,
                model_profile_id=model_profile_id,
                billing=billing,
                usage=usage_totals or None,
            )

    return {"chunks": len(chunks), "document_id": str(document_id)}


async def delete_document(job_id: uuid.UUID) -> dict:
    """Удаляет ассет и/или чанки+векторы документа (идемпотентно)."""
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"deleted": False}
        asset_id = job.input_json.get("asset_id")
        document_id = job.input_json.get("document_id")

        deleted_asset = False
        if asset_id:
            asset = await session.get(Asset, uuid.UUID(asset_id))
            if asset is not None:
                await get_blob_store().delete(asset.blob_key)
                await session.delete(asset)
                deleted_asset = True

        deleted_document = False
        if document_id:
            doc = await session.get(Document, uuid.UUID(document_id))
            if doc is not None:
                kb = await session.get(KnowledgeBase, doc.knowledge_base_id)
                if kb is not None:
                    collection = collection_name(kb.id, kb.embedding_version)
                    chunks = (
                        await session.execute(
                            select(Chunk).where(Chunk.document_id == doc.id)
                        )
                    ).scalars().all()
                    vector_ids = [c.vector_id for c in chunks]
                    if vector_ids:
                        await get_vector_store().delete_points(collection, vector_ids)
                    for c in chunks:
                        await session.delete(c)
                await session.delete(doc)
                deleted_document = True

        await session.commit()
        return {
            "deleted_asset_id": asset_id,
            "deleted_document_id": document_id,
            "deleted": deleted_asset or deleted_document,
        }


register_handler(JobType.DOCUMENT_INGEST.value)(ingest_document)
register_handler(JobType.DOCUMENT_DELETE.value)(delete_document)
