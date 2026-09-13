"""Каталог моделей: список профилей моделей пользователя.

Модели фильтруются по провайдеру пользователя и, опционально, по capability.
Capabilities хранятся в JSONB и управляют UI, а не условными ветками.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, ProviderCredential, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import ModelProfileOut

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=list[ModelProfileOut])
async def list_models(
    capability: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ModelProfileOut]:
    """Возвращает включённые модели пользователя, опционально по capability."""
    stmt = (
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.enabled.is_(True),
            ModelProfile.enabled.is_(True),
        )
        .order_by(ModelProfile.display_name)
    )
    if capability:
        stmt = stmt.where(ModelProfile.capabilities.contains([capability]))
    result = await session.execute(stmt)
    return [ModelProfileOut.model_validate(m) for m in result.scalars().all()]
