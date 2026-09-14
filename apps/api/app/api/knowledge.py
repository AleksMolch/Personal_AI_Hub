"""Эндпоинты баз знаний и RAG-запроса.

Загрузка документа создаёт document_ingest job. Query выполняет retrieval
с цитатами; при низкой релевантности возвращает sufficient=false.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from personal_hub.blobstore import get_blob_store
from personal_hub.db.engine import get_session
from personal_hub.jobs import JobType
from personal_hub.knowledge import MIN_RELEVANCE, collection_name
from personal_hub.models import (
    Asset,
    Chunk,
    Document,
    KnowledgeBase,
    ModelProfile,
    ProviderCredential,
    User,
)
from personal_hub.providers.base import ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.vectorstore import get_vector_store
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.job_service import create_job
from app.schemas import (
    Citation,
    DocumentCreateResponse,
    DocumentOut,
    KnowledgeBaseCreate,
    KnowledgeBaseDetail,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    QueryRequest,
    QueryResult,
)

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge"])


async def _owned_kb(session: AsyncSession, kb_id: uuid.UUID, user: User) -> KnowledgeBase:
    result = await session.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user.id
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "База знаний не найдена.")
    return kb


async def _owned_embedding_model(
    session: AsyncSession, user: User, model_profile_id: uuid.UUID
) -> ModelProfile:
    result = await session.execute(
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(ModelProfile.id == model_profile_id, ProviderCredential.user_id == user.id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель эмбеддингов не найдена.")
    return model


async def _embedding_connection(session: AsyncSession, kb: KnowledgeBase):
    if kb.embedding_model_profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не задана модель эмбеддингов.")
    model = await session.get(ModelProfile, kb.embedding_model_profile_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель эмбеддингов не найдена.")
    provider = await session.get(ProviderCredential, model.provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Провайдер эмбеддингов не найден.")
    return (
        ProviderConnection(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=get_cipher().decrypt(provider.encrypted_secret),
        ),
        model,
    )


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeBaseOut]:
    result = await session.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == user.id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    return [KnowledgeBaseOut.model_validate(kb) for kb in result.scalars().all()]


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBaseOut:
    model = await _owned_embedding_model(session, user, payload.embedding_model_profile_id)
    kb = KnowledgeBase(
        user_id=user.id,
        name=payload.name,
        embedding_model_profile_id=model.id,
        embedding_version=model.external_model_id,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return KnowledgeBaseOut.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseDetail)
async def get_knowledge_base(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBaseDetail:
    kb = await _owned_kb(session, kb_id, user)
    docs = (
        await session.execute(
            select(Document)
            .where(Document.knowledge_base_id == kb.id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    detail = KnowledgeBaseDetail.model_validate(kb)
    detail.documents = [DocumentOut.model_validate(d) for d in docs]
    return detail


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    payload: KnowledgeBaseUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBaseOut:
    kb = await _owned_kb(session, kb_id, user)
    data = payload.model_dump(exclude_unset=True)
    if data.get("embedding_model_profile_id"):
        model = await _owned_embedding_model(session, user, data["embedding_model_profile_id"])
        kb.embedding_model_profile_id = model.id
        kb.embedding_version = model.external_model_id
    if data.get("name"):
        kb.name = data["name"]
    await session.commit()
    await session.refresh(kb)
    return KnowledgeBaseOut.model_validate(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    kb = await _owned_kb(session, kb_id, user)
    # Векторы очищаются в фоне (см. delete_document) или здесь упрощённо.
    await session.delete(kb)
    await session.commit()


@router.post("/{kb_id}/documents", response_model=DocumentCreateResponse)
async def add_document(
    kb_id: uuid.UUID,
    file: UploadFile | None = File(default=None),
    asset_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentCreateResponse:
    """Загружает документ и ставит задачу индексации."""
    kb = await _owned_kb(session, kb_id, user)

    asset_ref: Asset | None = None
    if file is not None:
        store = get_blob_store()
        blob = await store.put(
            _iter_upload(file),
            {
                "original_name": file.filename or "unnamed",
                "mime_type": file.content_type or "application/octet-stream",
            },
            max_size=50 * 1024 * 1024,
        )
        asset = Asset(
            user_id=user.id,
            kind="document",
            status="ready",
            blob_key=blob.key,
            original_name=file.filename or "unnamed",
            mime_type=blob.mime_type,
            size_bytes=blob.size_bytes,
            sha256=blob.sha256,
        )
        session.add(asset)
        await session.flush()
        asset_ref = asset
        doc_title = title or file.filename or "unnamed"
    elif asset_id:
        asset_ref = await session.get(Asset, uuid.UUID(asset_id))
        if asset_ref is None or asset_ref.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден.")
        doc_title = title or asset_ref.original_name
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите файл или asset_id.")

    if asset_ref is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл не найден.")

    document = Document(
        knowledge_base_id=kb.id,
        asset_id=asset_ref.id,
        title=doc_title,
        status="pending",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    job = await create_job(
        session,
        user_id=user.id,
        job_type=JobType.DOCUMENT_INGEST.value,
        input_json={"document_id": str(document.id)},
        idempotency_key=f"ingest-{document.id}",
    )
    return DocumentCreateResponse(document_id=document.id, job_id=job.id)


async def _iter_upload(file: UploadFile):
    while chunk := await file.read(1024 * 1024):
        yield chunk


@router.post("/{kb_id}/query", response_model=QueryResult)
async def query_knowledge_base(
    kb_id: uuid.UUID,
    payload: QueryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QueryResult:
    """Выполняет retrieval по базе знаний с цитатами."""
    kb = await _owned_kb(session, kb_id, user)
    connection, model = await _embedding_connection(session, kb)

    adapter = get_adapter(connection.provider_type)
    result = await adapter.embed(connection, [payload.text], model.external_model_id)
    query_vector = result.vectors[0]

    hits = await get_vector_store().search(
        collection_name(kb.id, kb.embedding_version), query_vector, payload.top_k
    )

    citations: list[Citation] = []
    for hit in hits:
        if hit.score < MIN_RELEVANCE:
            continue
        document_id = hit.payload.get("document_id") or ""
        document = await session.get(Document, uuid.UUID(document_id)) if document_id else None
        citations.append(
            Citation(
                chunk_id=hit.id,
                document_id=document_id,
                document_title=document.title if document else "—",
                text=await _chunk_text(session, hit.id),
                page=hit.payload.get("page"),
                score=hit.score,
            )
        )

    return QueryResult(sufficient=bool(citations), citations=citations)


async def _chunk_text(session: AsyncSession, vector_id: str) -> str:
    result = await session.execute(select(Chunk).where(Chunk.vector_id == vector_id))
    chunk = result.scalar_one_or_none()
    return chunk.content if chunk else ""
