"""Каталог моделей: список профилей моделей пользователя.

Модели фильтруются по провайдеру пользователя и, опционально, по capability.
Capabilities хранятся в JSONB и управляют UI, а не условными ветками.

Дополнительно отдаётся признак `has_price`: он нужен интерфейсу, чтобы честно
предупредить о модели без настроенной цены (без цены платный вызов не уходит —
см. billing). Признак вычисляется одним запросом, а не по одной проверке на
модель, чтобы список не превращался в N+1.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import ModelProfileOut

router = APIRouter(prefix="/api/v1/models", tags=["models"])


async def _priced_model_ids(
    session: AsyncSession, user_id
) -> set:
    """Возвращает id моделей пользователя, у которых есть хотя бы один прайс.

    Один запрос вместо проверки по каждой модели: список моделей может быть
    большим (у OpenRouter сотни записей), и N+1 здесь заметен на UI.

    Args:
        session: Асинхронная сессия БД.
        user_id: Владелец провайдеров.

    Returns:
        Множество UUID профилей моделей, для которых задана цена.
    """
    stmt = (
        select(PriceSnapshot.model_profile_id)
        .join(ModelProfile, PriceSnapshot.model_profile_id == ModelProfile.id)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(ProviderCredential.user_id == user_id)
        .distinct()
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


@router.get("", response_model=list[ModelProfileOut])
async def list_models(
    capability: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ModelProfileOut]:
    """Возвращает включённые модели пользователя, опционально по capability.

    Args:
        capability: Необязательный фильтр по capability (например `chat`).
        user: Текущий пользователь.
        session: Асинхронная сессия БД.

    Returns:
        Список моделей с признаком наличия цены (`has_price`).
    """
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
    models = result.scalars().all()
    priced = await _priced_model_ids(session, user.id)

    return [
        ModelProfileOut.model_validate(m).model_copy(
            update={"has_price": m.id in priced}
        )
        for m in models
    ]
