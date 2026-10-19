"""Эндпоинты цен моделей (versioned PriceSnapshot).

POST создаёт новый снапшот; GET возвращает историю цен модели. Отдельный
эндпоинт `/prices/extract` разбирает страницу тарифов провайдера и возвращает
кандидатов на цены — БЕЗ сохранения: значения обязан подтвердить пользователь.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from personal_hub.pricing_import import (
    PriceImportError,
    extract_price_candidates,
    fetch_pricing_page,
    html_to_lines,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import (
    PriceCreate,
    PriceImportCandidate,
    PriceImportRequest,
    PriceImportResult,
    PriceOut,
)

router = APIRouter(prefix="/api/v1/prices", tags=["prices"])


async def _owned_model(
    session: AsyncSession, user: User, model_profile_id: uuid.UUID
) -> ModelProfile:
    result = await session.execute(
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(
            ModelProfile.id == model_profile_id,
            ProviderCredential.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель не найдена.")
    return model


@router.get("", response_model=list[PriceOut])
async def list_prices(
    model_profile_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PriceOut]:
    stmt = select(PriceSnapshot).order_by(PriceSnapshot.effective_at.desc())
    if model_profile_id is not None:
        await _owned_model(session, user, model_profile_id)
        stmt = stmt.where(PriceSnapshot.model_profile_id == model_profile_id)
    else:
        # Только модели пользователя.
        subq = (
            select(ModelProfile.id)
            .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
            .where(ProviderCredential.user_id == user.id)
        )
        stmt = stmt.where(PriceSnapshot.model_profile_id.in_(subq))
    result = await session.execute(stmt.limit(200))
    return [PriceOut.model_validate(p) for p in result.scalars().all()]


@router.post("/extract", response_model=PriceImportResult)
async def extract_prices(
    payload: PriceImportRequest,
    user: User = Depends(get_current_user),
) -> PriceImportResult:
    """Разбирает страницу тарифов и возвращает кандидатов на цены.

    Ничего не сохраняет: провайдеры не дают машинно-читаемого контракта на
    страницу тарифов, поэтому найденные значения — только подсказка. Пользователь
    обязан сверить их со страницей и подтвердить через `POST /prices`.

    Args:
        payload: Адрес страницы тарифов.
        user: Текущий пользователь (эндпоинт доступен только авторизованным).

    Returns:
        Кандидаты с фрагментами текста и напоминанием о проверке.

    Raises:
        HTTPException: 400 при некритичных ошибках (редирект, размер, HTML-код);
            502 при недоступности сайта; 403 при попытке загрузить внутренний
            адрес.
    """
    try:
        html = await fetch_pricing_page(payload.url)
    except PriceImportError as exc:
        status_code = {
            "PRICE_IMPORT_FORBIDDEN_HOST": status.HTTP_403_FORBIDDEN,
            "PRICE_IMPORT_UNREACHABLE": status.HTTP_502_BAD_GATEWAY,
            "PRICE_IMPORT_TIMEOUT": status.HTTP_502_BAD_GATEWAY,
        }.get(exc.code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code, f"{exc.message} ({exc.code})") from exc

    lines = html_to_lines(html)
    candidates = extract_price_candidates("\n".join(lines))

    return PriceImportResult(
        source_url=payload.url,
        candidates=[
            PriceImportCandidate(
                field=candidate.field,
                value=candidate.value,
                snippet=candidate.snippet,
                confidence=candidate.confidence,
            )
            for candidate in candidates
        ],
        note=(
            "Значения найдены автоматически и могут быть неверными: страницы "
            "тарифов меняются, а единицы измерения у провайдеров различаются. "
            "Сверьте каждое значение со страницей провайдера и только потом "
            "сохраняйте цену."
        ),
    )


@router.post("", response_model=PriceOut, status_code=status.HTTP_201_CREATED)
async def create_price(
    payload: PriceCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceOut:
    """Создаёт новую версию цены модели (не изменяет исторические записи)."""
    await _owned_model(session, user, payload.model_profile_id)
    snapshot = PriceSnapshot(
        model_profile_id=payload.model_profile_id,
        currency=payload.currency.upper(),
        input_per_million=payload.input_per_million,
        output_per_million=payload.output_per_million,
        cache_read_per_million=payload.cache_read_per_million,
        cache_write_per_million=payload.cache_write_per_million,
        source=payload.source,
        source_url=payload.source_url,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return PriceOut.model_validate(snapshot)
