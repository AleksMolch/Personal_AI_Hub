"""Эндпоинты бюджетов: чтение и обновление лимитов.

Один бюджет на пользователя; лимиты и валюта обновляются атомарно.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from personal_hub.db.engine import get_session
from personal_hub.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import get_or_create_budget
from app.deps import get_current_user
from app.schemas import BudgetOut, BudgetUpdate

router = APIRouter(prefix="/api/v1/budgets", tags=["budgets"])


@router.get("", response_model=BudgetOut)
async def get_budget(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BudgetOut:
    budget = await get_or_create_budget(session, user.id)
    await session.commit()
    return BudgetOut.model_validate(budget)


@router.put("", response_model=BudgetOut)
async def update_budget(
    payload: BudgetUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BudgetOut:
    budget = await get_or_create_budget(session, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(budget, field, value)
    await session.commit()
    await session.refresh(budget)
    return BudgetOut.model_validate(budget)
