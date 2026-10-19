"""Каталог моделей: список профилей, ручное уточнение возможностей.

Модели фильтруются по провайдеру пользователя и, опционально, по capability.
Capabilities хранятся в JSONB и управляют UI, а не условными ветками.

Дополнительно отдаётся признак `has_price`: он нужен интерфейсу, чтобы честно
предупредить о модели без настроенной цены (без цены платный вызов не уходит —
см. billing). Признак вычисляется одним запросом, а не по одной проверке на
модель, чтобы список не превращался в N+1.

PATCH позволяет объявить возможности вручную: провайдер не всегда рекламирует
поддержку параметров (DeepSeek принимает `reasoning_effort`, но не перечисляет
его в `/models`), и без этого интерфейс скрывал бы доступную функцию.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import ModelProfileOut, ModelUpdate

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


@router.patch("/{model_id}", response_model=ModelProfileOut)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ModelProfileOut:
    """Уточняет возможности модели вручную.

    Провайдер не всегда сообщает о поддержке параметров: DeepSeek принимает
    `reasoning_effort`, но в `/models` этого не указывает. Без ручного
    объявления интерфейс прятал бы селектор глубины рассуждений, хотя модель её
    поддерживает. Значения проверяются по белому списку.

    Args:
        model_id: Идентификатор профиля модели.
        payload: Новый список capabilities (или None, чтобы не менять).
        user: Текущий пользователь (проверяется владение провайдером).
        session: Асинхронная сессия БД.

    Returns:
        Обновлённый профиль модели с признаком наличия цены.

    Raises:
        HTTPException: 404, если модель не принадлежит пользователю.
    """
    model = await _owned_model(session, model_id, user)
    if payload.capabilities is not None:
        # capabilities — данные: заменяем список целиком, сохраняя базовые
        # возможности (chat/streaming), которые выставляет синхронизация.
        preserved = [
            cap
            for cap in (model.capabilities or [])
            if cap not in ModelUpdate.ALLOWED
        ]
        model.capabilities = sorted(set(preserved) | set(payload.capabilities))
        await session.commit()
        await session.refresh(model)

    priced = await _priced_model_ids(session, user.id)
    return ModelProfileOut.model_validate(model).model_copy(
        update={"has_price": model.id in priced}
    )


async def _owned_model(
    session: AsyncSession, model_id: uuid.UUID, user: User
) -> ModelProfile:
    """Возвращает модель пользователя или 404.

    Args:
        session: Асинхронная сессия БД.
        model_id: Идентификатор профиля модели.
        user: Текущий пользователь.

    Returns:
        Профиль модели, принадлежащий провайдеру пользователя.

    Raises:
        HTTPException: 404, если модели нет или она чужая.
    """
    stmt = (
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(
            ModelProfile.id == model_id,
            ProviderCredential.user_id == user.id,
        )
    )
    model = (await session.execute(stmt)).scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель не найдена.")
    return model
