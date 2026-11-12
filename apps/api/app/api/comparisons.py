"""Сравнение моделей side-by-side: один промпт, два ответа.

Оба вызова проходят через бюджетный контур (резервирование до вызова,
финализация по фактическому usage), поэтому сравнение учитывается в лимитах
пользователя. Без цены модели вызов разрешён, но стоимость остаётся unknown
(как и в чате).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from personal_hub.db.engine import get_session
from personal_hub.models import User
from personal_hub.providers.base import ChatMessage, ChatRequest
from personal_hub.providers.registry import get_adapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import _connection_for, _resolve_model
from app.billing import (
    cancel_external_call,
    estimate_units,
    get_latest_price,
    reserve_external_call,
    settle_external_call,
)
from app.deps import get_current_user
from app.schemas import ComparisonItem, ComparisonRequest, ComparisonResult

router = APIRouter(prefix="/api/v1/comparisons", tags=["comparisons"])


@router.post("", response_model=ComparisonResult)
async def compare_models(
    payload: ComparisonRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ComparisonResult:
    """Запускает один промпт на двух моделях и возвращает оба ответа.

    Порядок ответов повторяет `model_profile_ids`. Модели должны принадлежать
    пользователю; дубликаты не запрещены (можно сравнить и одинаковые).
    """
    results: list[ComparisonItem] = []
    for model_profile_id in payload.model_profile_ids:
        model, provider = await _resolve_model(session, user, model_profile_id)
        price = await get_latest_price(session, model.id)

        units = estimate_units(payload.prompt, model.output_limit)
        units["operation"] = "comparison"
        billing = None
        if price is not None:
            billing = await reserve_external_call(
                session, user.id, price=price, units=units
            )

        adapter = get_adapter(provider.provider_type)
        request = ChatRequest(
            model=model.external_model_id,
            messages=[ChatMessage(role="user", content=payload.prompt)],
            system=payload.system,
        )
        try:
            completion = await adapter.chat_complete(_connection_for(provider), request)
        except Exception:
            if billing is not None:
                await cancel_external_call(session, billing=billing)
            raise

        if billing is not None:
            await settle_external_call(
                session,
                user_id=user.id,
                provider_id=provider.id,
                model_profile_id=model.id,
                billing=billing,
                usage=completion.usage,
                estimated_units=units,
            )

        results.append(
            ComparisonItem(
                model_profile_id=model.id,
                display_name=model.display_name,
                content=completion.text,
                usage=completion.usage,
            )
        )

    return ComparisonResult(results=results)
