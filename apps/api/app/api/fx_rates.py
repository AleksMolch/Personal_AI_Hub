"""Эндпоинты валютных курсов (FxRate).

Позволяют задавать курсы конвертации валют вручную; конвертация в биллинге
использует последний сохранённый курс (см. app/billing.convert_to_base).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from personal_hub.db.engine import get_session
from personal_hub.models import FxRate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import FxRateCreate, FxRateOut

router = APIRouter(prefix="/api/v1/fx-rates", tags=["fx-rates"])


@router.get("", response_model=list[FxRateOut])
async def list_fx_rates(
    _=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FxRateOut]:
    result = await session.execute(
        select(FxRate).order_by(FxRate.fetched_at.desc()).limit(200)
    )
    return [FxRateOut.model_validate(r) for r in result.scalars().all()]


@router.post("", response_model=FxRateOut, status_code=status.HTTP_201_CREATED)
async def create_fx_rate(
    payload: FxRateCreate,
    _=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FxRateOut:
    rate = FxRate(
        from_currency=payload.from_currency.upper(),
        to_currency=payload.to_currency.upper(),
        rate=payload.rate,
        source=payload.source,
    )
    session.add(rate)
    await session.commit()
    await session.refresh(rate)
    return FxRateOut.model_validate(rate)
