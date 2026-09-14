"""Эндпоинты цен моделей (versioned PriceSnapshot).

POST создаёт новый снапшот; GET возвращает историю цен модели.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import PriceCreate, PriceOut

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
