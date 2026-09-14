"""Обработчики задач индексации документов и удаления.

document_ingest: parse -> chunk -> embed -> Qdrant + Chunk rows.
document_delete: удаление ассета и/или чанков+векторов документа.
"""
from __future__ import annotations

import logging
import uuid

from personal_hub.blobstore import get_blob_store
from personal_hub.chunking import chunk_document
from personal_hub.db.engine import get_session_factory
from personal_hub.jobs import JobType
from personal_hub.knowledge import collection_name
from personal_hub.models import (
    Asset,
    Chunk,
    Document,
    Job,
    KnowledgeBase,
    ModelProfile,
    ProviderCredential,
)
from personal_hub.parsing import UnsupportedFormatError, parse_document
from personal_hub.providers.base import ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.vectorstore import VectorPoint, get_vector_store
from sqlalchemy import select

from worker.tasks.jobs import register_handler

logger = logging.getLogger("worker.ingest")

EMBED_BATCH_SIZE = 32


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
    """Индексирует документ: parse -> chunk -> embed -> Qdrant + Chunk rows."""
    factory = get_session_factory()
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
        asset_key = asset.blob_key
        asset_filename = asset.original_name
        asset_mime = asset.mime_type
        collection = collection_name(kb.id, kb.embedding_version)
        embedding_model = model.external_model_id

    try:
        store = get_blob_store()
        data = b"".join([c async for c in store.open(asset_key)])
        pages = parse_document(asset_filename, asset_mime, data)
    except UnsupportedFormatError as exc:
        await _set_document_status(document_id, "failed", exc.code)
        raise

    chunks = chunk_document(pages)
    if not chunks:
        await _set_document_status(document_id, "failed", "EMPTY_DOCUMENT")
        raise ValueError("документ не содержит текста")

    adapter = get_adapter(connection.provider_type)
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        result = await adapter.embed(connection, [c.text for c in batch], embedding_model)
        vectors.extend(result.vectors)

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
