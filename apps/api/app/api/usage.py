"""Эндпоинты расходов: сводка и список записей.

Сводка агрегирует стоимость и токены за день/месяц. Список записей
поддерживает пагинацию (limit/offset).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from personal_hub.db.engine import get_session
from personal_hub.models import UsageRecord, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import get_or_create_budget
from app.deps import get_current_user
from app.schemas import UsageRecordOut, UsageSummary

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


def _start_of_day() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/summary", response_model=UsageSummary)
async def usage_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageSummary:
    day_start = _start_of_day()
    month_start = _start_of_month()

    records = (
        await session.execute(
            select(UsageRecord).where(
                UsageRecord.user_id == user.id, UsageRecord.occurred_at >= month_start
            )
        )
    ).scalars().all()

    today_cost = sum(
        (r.cost_amount for r in records if r.occurred_at >= day_start), start=Decimal(0)
    )
    month_cost = sum((r.cost_amount for r in records), start=Decimal(0))

    def _tokens(key: str, since: datetime) -> int:
        return sum(int(r.units_json.get(key, 0)) for r in records if r.occurred_at >= since)

    budget = await get_or_create_budget(session, user.id)

    daily_remaining = None
    monthly_remaining = None
    if budget.daily_limit is not None:
        daily_remaining = budget.daily_limit - today_cost
    if budget.monthly_limit is not None:
        monthly_remaining = budget.monthly_limit - month_cost

    return UsageSummary(
        currency=budget.currency,
        today_cost=today_cost,
        month_cost=month_cost,
        today_input_tokens=_tokens("input_tokens", day_start),
        today_output_tokens=_tokens("output_tokens", day_start),
        month_input_tokens=_tokens("input_tokens", month_start),
        month_output_tokens=_tokens("output_tokens", month_start),
        daily_limit=budget.daily_limit,
        monthly_limit=budget.monthly_limit,
        daily_remaining=daily_remaining,
        monthly_remaining=monthly_remaining,
    )


@router.get("/records", response_model=list[UsageRecordOut])
async def usage_records(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[UsageRecordOut]:
    result = await session.execute(
        select(UsageRecord)
        .where(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [UsageRecordOut.model_validate(r) for r in result.scalars().all()]
