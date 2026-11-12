"""Сквозной сценарий «таблицы + документы в одном ответе».

Один вопрос может обращаться к базе знаний (RAG-цитаты) и/или к таблице
(авто-SQL через DuckDB read-only sandbox), а затем синтезировать единый ответ
с цитатами и результатом таблицы. Все платные вызовы проходят через бюджетный
контур; без цены chat-модели синтез и генерация SQL пропускаются (но retrieval
по эмбеддингам, если задан kb_id, выполняется по своей цене).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.blobstore import get_blob_store
from personal_hub.db.engine import get_session
from personal_hub.models import Asset, ModelProfile, ProviderCredential, User
from personal_hub.providers.base import ChatMessage, ChatRequest, ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.tables import load_table, run_query, schema_preview
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.knowledge import _owned_kb, _retrieve_citations
from app.billing import (
    cancel_external_call,
    estimate_units,
    get_latest_price,
    reserve_external_call,
    settle_external_call,
)
from app.deps import get_current_user
from app.schemas import AskRequest, AskResult, Citation, TableAnswer

router = APIRouter(prefix="/api/v1/ask", tags=["ask"])

_SQL_SYSTEM = (
    "Ты пишешь SQL для DuckDB. Отвечай ТОЛЬКО одним запросом SELECT или WITH, "
    "без пояснений и без точки с запятой в конце. Таблица называется data."
)


async def _owned_asset(session: AsyncSession, asset_id: uuid.UUID, user: User) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден.")
    return asset


async def _chat_once(
    session: AsyncSession,
    user: User,
    model: ModelProfile,
    provider: ProviderCredential,
    price,
    system: str | None,
    user_text: str,
    operation: str,
) -> str:
    """Один оплачиваемый chat_complete с резервированием и финализацией."""
    units = estimate_units(user_text, model.output_limit)
    units["operation"] = operation
    billing = await reserve_external_call(session, user.id, price=price, units=units)

    connection = ProviderConnection(
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=get_cipher().decrypt(provider.encrypted_secret),
    )
    adapter = get_adapter(provider.provider_type)
    request = ChatRequest(
        model=model.external_model_id,
        messages=[ChatMessage(role="user", content=user_text)],
        system=system,
    )
    try:
        completion = await adapter.chat_complete(connection, request)
    except Exception:
        await cancel_external_call(session, billing=billing)
        raise

    await settle_external_call(
        session,
        user_id=user.id,
        provider_id=provider.id,
        model_profile_id=model.id,
        billing=billing,
        usage=completion.usage,
        estimated_units=units,
    )
    return completion.text


async def _resolve_chat_model(
    session: AsyncSession, user: User, model_id: uuid.UUID | None
) -> tuple[ModelProfile, ProviderCredential]:
    if model_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите модель.")
    result = await session.execute(
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(ModelProfile.id == model_id, ProviderCredential.user_id == user.id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель не найдена.")
    provider = await session.get(ProviderCredential, model.provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Провайдер модели не найден.")
    return model, provider


@router.post("", response_model=AskResult)
async def ask(
    payload: AskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AskResult:
    """Собирает ответ по документам и/или таблице, синтезирует единый ответ."""
    citations: list[Citation] = []
    table: TableAnswer | None = None

    # 1. Retrieval по базе знаний (необязательно).
    if payload.kb_id is not None:
        kb = await _owned_kb(session, payload.kb_id, user)
        citations = await _retrieve_citations(
            session, user, kb, payload.question, top_k=5
        )

    # 2. Таблица: генерация SQL и выполнение (необязательно).
    sql: str | None = None
    if payload.table_asset_id is not None:
        asset = await _owned_asset(session, payload.table_asset_id, user)
        path = str(get_blob_store().path_for(asset.blob_key))
        fmt = "xlsx" if asset.original_name.lower().endswith((".xlsx", ".xls")) else "csv"
        conn = load_table(path, fmt)
        schema = schema_preview(conn)

        model, provider = await _resolve_chat_model(session, user, payload.chat_model_profile_id)
        price = await get_latest_price(session, model.id)
        if price is None:
            sql = None
        else:
            schema_text = "\n".join(
                f"- {c['name']} ({c['type']})" for c in schema["columns"]
            )
            sql = await _chat_once(
                session, user, model, provider, price, _SQL_SYSTEM,
                f"Схема таблицы data:\n{schema_text}\n\nВопрос: {payload.question}",
                "ask_sql_generation",
            )
            result = run_query(conn, sql.strip())
            table = TableAnswer(columns=result["columns"], rows=result["rows"], sql=sql)

    # 3. Синтез единого ответа.
    answer: str | None = None
    answer_skipped_reason: str | None = None
    if payload.chat_model_profile_id is None:
        answer_skipped_reason = "model_not_found"
    elif not citations and table is None:
        answer_skipped_reason = "no_sources"
    else:
        model, provider = await _resolve_chat_model(session, user, payload.chat_model_profile_id)
        price = await get_latest_price(session, model.id)
        if price is None:
            answer_skipped_reason = "price_missing"
        else:
            context_parts: list[str] = []
            for i, c in enumerate(citations, start=1):
                src = c.document_title + (f", стр. {c.page}" if c.page else "")
                context_parts.append(f"[{i}] ({src}): {c.text}")
            if table is not None:
                rows = "\n".join(" | ".join(str(v) for v in row) for row in table.rows)
                context_parts.append(
                    f"Результат SQL ({', '.join(table.columns)}):\n{rows}"
                )
            prompt = (
                "Ответь на вопрос, используя только приведённые источники. "
                "Если данных недостаточно, скажи об этом.\n\n"
                f"Вопрос: {payload.question}\n\n" + "\n\n".join(context_parts)
            )
            answer = await _chat_once(
                session, user, model, provider, price, None, prompt, "ask_synthesis"
            )

    return AskResult(
        answer=answer,
        answer_skipped_reason=answer_skipped_reason,
        citations=citations,
        table=table,
    )
