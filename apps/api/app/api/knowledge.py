"""Эндпоинты баз знаний и RAG-запроса.

Загрузка документа создаёт document_ingest job. Query выполняет retrieval
с цитатами; при низкой релевантности возвращает sufficient=false. Embedding
запроса и LLM-синтез ответа проходят через бюджетный контур (резервирование/
UsageRecord), чтобы платные вызовы не обходили лимиты пользователя.
"""
from __future__ import annotations

import logging
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
from personal_hub.providers.base import ChatMessage, ChatRequest, ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.vectorstore import get_vector_store
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import (
    cancel_external_call,
    embedding_units,
    estimate_units,
    get_latest_price,
    reserve_external_call,
    settle_external_call,
)
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

logger = logging.getLogger("api.knowledge")

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
    """Выполняет retrieval по базе знаний с цитатами (embedding оплачивается)."""
    kb = await _owned_kb(session, kb_id, user)
    connection, model = await _embedding_connection(session, kb)

    # Embedding запроса — платный вызов: при наличии цены резервируем бюджет
    # ДО вызова, фиксируем расход после (смотри billing.py).
    price = await get_latest_price(session, model.id)
    billing = None
    if price is not None:
        billing = await reserve_external_call(
            session,
            user.id,
            price=price,
            units=embedding_units(payload.text, "rag_query_embedding"),
        )

    adapter = get_adapter(connection.provider_type)
    try:
        result = await adapter.embed(connection, [payload.text], model.external_model_id)
    except Exception:
        if billing is not None:
            await cancel_external_call(session, billing=billing)
        raise
    query_vector = result.vectors[0]

    if billing is not None:
        await settle_external_call(
            session,
            user_id=user.id,
            provider_id=model.provider_id,
            model_profile_id=model.id,
            billing=billing,
            usage=None,
        )

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

    answer: str | None = None
    if citations and payload.chat_model_profile_id is not None:
        answer = await _synthesize(
            session, user, payload.chat_model_profile_id, payload.text, citations
        )

    return QueryResult(sufficient=bool(citations), answer=answer, citations=citations)


async def _synthesize(
    session: AsyncSession,
    user: User,
    chat_model_profile_id: uuid.UUID,
    question: str,
    citations: list[Citation],
) -> str | None:
    """Синтезирует ответ по найденным фрагментам с цитатами (оплачивается).

    Требуется заданная цена модели: если цена неизвестна, синтез не выполняется
    (answer=None) — платный вызов без контроля бюджета запрещён.
    """
    chat_model = await session.get(ModelProfile, chat_model_profile_id)
    if chat_model is None:
        return None
    provider = await session.get(ProviderCredential, chat_model.provider_id)
    if provider is None or provider.user_id != user.id:
        return None

    price = await get_latest_price(session, chat_model.id)
    if price is None:
        logger.info("synthesis_no_price model=%s", chat_model.external_model_id)
        return None

    connection = ProviderConnection(
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=get_cipher().decrypt(provider.encrypted_secret),
    )

    context_parts = []
    for i, c in enumerate(citations, start=1):
        src = c.document_title + (f", стр. {c.page}" if c.page else "")
        context_parts.append(f"[{i}] ({src}): {c.text}")
    context = "\n\n".join(context_parts)

    system = (
        "Отвечай на вопрос строго по приведённым фрагментам. Ссылайся на источники "
        "в квадратных скобках, например [1]. Если в фрагментах нет ответа, ответь: "
        "«В документах недостаточно оснований для ответа». Не выдумывай."
    )
    user_msg = f"Вопрос: {question}\n\nФрагменты:\n{context}"

    request = ChatRequest(
        model=chat_model.external_model_id,
        messages=[ChatMessage(role="user", content=user_msg)],
        system=system,
    )

    billing = await reserve_external_call(
        session,
        user.id,
        price=price,
        units={**estimate_units(user_msg, None), "operation": "rag_synthesis"},
    )

    adapter = get_adapter(provider.provider_type)
    try:
        answer = await adapter.chat_complete(connection, request)
    except Exception:
        await cancel_external_call(session, billing=billing)
        raise

    await settle_external_call(
        session,
        user_id=user.id,
        provider_id=provider.id,
        model_profile_id=chat_model.id,
        billing=billing,
        usage=None,
    )
    return answer


async def _chunk_text(session: AsyncSession, vector_id: str) -> str:
    result = await session.execute(select(Chunk).where(Chunk.vector_id == vector_id))
    chunk = result.scalar_one_or_none()
    return chunk.content if chunk else ""
