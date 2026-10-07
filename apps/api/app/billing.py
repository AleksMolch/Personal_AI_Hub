"""Биллинг: бюджеты, резервирование, расчёт и запись расходов.

Бюджет хранится в базовой валюте; стоимости конвертируются только через
сохранённый FxRate (без молчаливого смешивания валют). Резервирование
происходит до вызова провайдера, settlement — после.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from personal_hub.budget import BudgetExceededError, BudgetPeriod
from personal_hub.costs import (
    DEFAULT_OUTPUT_TOKENS,
    compute_cost,
    estimate_cost,
    estimate_tokens,
    parse_usage,
)
from personal_hub.models import (
    Budget,
    CostReservation,
    CostState,
    FxRate,
    PriceSnapshot,
    ReservationStatus,
    UsageRecord,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

RESERVATION_TTL_SECONDS = 300  # 5 минут
_CENTS = Decimal("0.00000001")


class CurrencyConversionError(Exception):
    """Нет курса для конвертации валют."""

    def __init__(self, from_currency: str, to_currency: str) -> None:
        super().__init__(f"Нет курса {from_currency}→{to_currency}.")
        self.code = "FX_RATE_MISSING"


@dataclass(frozen=True)
class BillingContext:
    """Данные для финализации расходов фоновой генерацией."""

    reservation_id: uuid.UUID
    price_snapshot_id: uuid.UUID
    input_per_million: Decimal
    output_per_million: Decimal
    cache_read_per_million: Decimal | None
    currency: str
    base_currency: str
    estimated_units: dict
    estimated_cost: Decimal


def _now() -> datetime:
    return datetime.now(UTC)


def _start_of_day(dt: datetime | None = None) -> datetime:
    dt = dt or _now()
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month(dt: datetime | None = None) -> datetime:
    dt = dt or _now()
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


async def get_or_create_budget(session: AsyncSession, user_id: uuid.UUID) -> Budget:
    budget = await session.scalar(select(Budget).where(Budget.user_id == user_id))
    if budget is None:
        budget = Budget(user_id=user_id)
        session.add(budget)
        await session.flush()
    return budget


async def _lock_budget(session: AsyncSession, user_id: uuid.UUID) -> Budget:
    """Гарантирует строку бюджета и блокирует её (SELECT FOR UPDATE).

    Блокировка сериализует параллельные проверки лимита: второй запрос ждёт
    коммита первого и видит обновлённый остаток, не обходя бюджет.
    """
    # INSERT ... ON CONFLICT DO NOTHING — идемпотентно создаёт строку без гонки.
    stmt = pg_insert(Budget).values(
        id=uuid.uuid4(), user_id=user_id, currency="USD"
    ).on_conflict_do_nothing(index_elements=["user_id"])
    await session.execute(stmt)
    budget = await session.scalar(
        select(Budget).where(Budget.user_id == user_id).with_for_update()
    )
    if budget is None:  # практически недостижимо после ON CONFLICT DO NOTHING
        raise RuntimeError("не удалось создать/заблокировать бюджет")
    return budget


async def get_latest_price(
    session: AsyncSession, model_profile_id: uuid.UUID
) -> PriceSnapshot | None:
    result = await session.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.model_profile_id == model_profile_id)
        .order_by(PriceSnapshot.effective_at.desc(), PriceSnapshot.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def convert_to_base(
    session: AsyncSession, amount: Decimal, from_currency: str, base_currency: str
) -> tuple[Decimal, uuid.UUID | None]:
    """Конвертирует сумму в базовую валюту, возвращая (сумма, fx_rate_id)."""
    if from_currency.upper() == base_currency.upper():
        return _money(amount), None
    result = await session.execute(
        select(FxRate)
        .where(
            FxRate.from_currency == from_currency.upper(),
            FxRate.to_currency == base_currency.upper(),
        )
        .order_by(FxRate.fetched_at.desc())
        .limit(1)
    )
    rate = result.scalar_one_or_none()
    if rate is None:
        raise CurrencyConversionError(from_currency, base_currency)
    return _money(amount * rate.rate), rate.id


async def _period_spend(
    session: AsyncSession, user_id: uuid.UUID, start: datetime
) -> Decimal:
    result = await session.execute(
        select(func.coalesce(func.sum(UsageRecord.cost_amount), 0)).where(
            UsageRecord.user_id == user_id, UsageRecord.occurred_at >= start
        )
    )
    return Decimal(result.scalar_one())


async def _active_reservations(
    session: AsyncSession, user_id: uuid.UUID, start: datetime
) -> Decimal:
    result = await session.execute(
        select(func.coalesce(func.sum(CostReservation.amount), 0)).where(
            CostReservation.user_id == user_id,
            CostReservation.status == ReservationStatus.ACTIVE.value,
            CostReservation.created_at >= start,
            CostReservation.expires_at > _now(),
        )
    )
    return Decimal(result.scalar_one())


async def check_and_reserve(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    price: PriceSnapshot,
    estimated_units: dict,
    message_id: uuid.UUID | None,
) -> BillingContext:
    """Проверяет бюджет и резервирует оценочную сумму.

    Возвращает BillingContext с данными для финализации. При превышении
    бросает BudgetExceededError (до отправки провайдеру).
    """
    estimated_amount = estimate_cost(
        estimated_units["input_tokens"], estimated_units["output_tokens"], price
    )
    # Ленивое освобождение просроченных резервирований перед проверкой.
    await reconcile_expired_reservations(session)
    budget = await _lock_budget(session, user_id)
    base_amount, _ = await convert_to_base(
        session, estimated_amount, price.currency, budget.currency
    )

    now = _now()
    day_start = _start_of_day(now)
    month_start = _start_of_month(now)

    if budget.daily_limit is not None:
        spend = await _period_spend(session, user_id, day_start)
        reserved = await _active_reservations(session, user_id, day_start)
        available = budget.daily_limit - spend - reserved
        if base_amount > available:
            raise BudgetExceededError(
                BudgetPeriod.DAILY, str(budget.daily_limit), str(available)
            )

    if budget.monthly_limit is not None:
        spend_m = await _period_spend(session, user_id, month_start)
        reserved_m = await _active_reservations(session, user_id, month_start)
        available_m = budget.monthly_limit - spend_m - reserved_m
        if base_amount > available_m:
            raise BudgetExceededError(
                BudgetPeriod.MONTHLY, str(budget.monthly_limit), str(available_m)
            )

    reservation = CostReservation(
        user_id=user_id,
        message_id=message_id,
        amount=base_amount,
        currency=budget.currency,
        status=ReservationStatus.ACTIVE.value,
        expires_at=now + timedelta(seconds=RESERVATION_TTL_SECONDS),
    )
    session.add(reservation)
    await session.flush()

    return BillingContext(
        reservation_id=reservation.id,
        price_snapshot_id=price.id,
        input_per_million=price.input_per_million,
        output_per_million=price.output_per_million,
        cache_read_per_million=price.cache_read_per_million,
        currency=price.currency,
        base_currency=budget.currency,
        estimated_units=estimated_units,
        estimated_cost=estimated_amount,
    )


async def release_reservation(session: AsyncSession, reservation_id: uuid.UUID) -> None:
    """Отменяет резервирование (генерация не состоялась/отменена)."""
    reservation = await session.get(CostReservation, reservation_id)
    if reservation is not None and reservation.status == ReservationStatus.ACTIVE.value:
        reservation.status = ReservationStatus.CANCELLED.value
        await session.flush()


async def finalize_generation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_profile_id: uuid.UUID,
    message_id: uuid.UUID | None,
    usage: dict | None,
    billing: BillingContext,
    provider_request_id: str | None,
    estimated_units: dict | None = None,
) -> UsageRecord | None:
    """Фиксирует расход и закрывает резервирование после генерации.

    Если провайдер вернул usage — cost_state=actual, иначе estimated на основе
    предварительной оценки. `estimated_units` позволяет посчитать оценку по
    частично выполненному вызову (например, часть батчей embeddings дошла).
    """
    price = PriceSnapshot(
        model_profile_id=model_profile_id,
        currency=billing.currency,
        input_per_million=billing.input_per_million,
        output_per_million=billing.output_per_million,
        cache_read_per_million=billing.cache_read_per_million,
    )

    if usage:
        units = parse_usage(usage)
        # operation — метаданные вызова; parse_usage возвращает только токены.
        operation = (billing.estimated_units or {}).get("operation")
        if operation:
            units["operation"] = operation
        cost = compute_cost(units, price)
        cost_state = CostState.ACTUAL.value
    else:
        units = estimated_units or billing.estimated_units
        cost = (
            estimate_cost(units["input_tokens"], units["output_tokens"], price)
            if estimated_units is not None
            else billing.estimated_cost
        )
        cost_state = CostState.ESTIMATED.value

    base_cost, fx_id = await convert_to_base(
        session, cost, billing.currency, billing.base_currency
    )

    record = UsageRecord(
        user_id=user_id,
        provider_id=provider_id,
        model_profile_id=model_profile_id,
        message_id=message_id,
        units_json=units,
        cost_amount=base_cost,
        currency=billing.base_currency,
        cost_state=cost_state,
        price_snapshot_id=billing.price_snapshot_id,
        fx_rate_id=fx_id,
        provider_request_id=provider_request_id,
    )
    session.add(record)

    reservation = await session.get(CostReservation, billing.reservation_id)
    if reservation is not None and reservation.status == ReservationStatus.ACTIVE.value:
        reservation.status = ReservationStatus.SETTLED.value

    await session.flush()
    return record


async def reconcile_expired_reservations(session: AsyncSession) -> int:
    """Отменяет просроченные активные резервирования; возвращает их число."""
    from typing import cast

    from sqlalchemy import update
    from sqlalchemy.engine import CursorResult

    result = await session.execute(
        update(CostReservation)
        .where(
            CostReservation.status == ReservationStatus.ACTIVE.value,
            CostReservation.expires_at <= _now(),
        )
        .values(status=ReservationStatus.CANCELLED.value)
    )
    await session.flush()
    return cast(CursorResult, result).rowcount or 0


def estimate_units(messages_text: str, output_limit: int | None) -> dict:
    """Оценивает единицы запроса: {input_tokens, output_tokens}."""
    input_tokens = estimate_tokens(messages_text)
    output_tokens = output_limit or DEFAULT_OUTPUT_TOKENS
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


# ---------------------------------------------------------------------------
# Помощники для внешних платных вызовов МИМО чат-потока (embeddings, синтез).
# Они используют тот же контур резервирования/финализации, что и чат, чтобы
# бюджеты учитывали все расходы пользователя, а не только генерации.
# ---------------------------------------------------------------------------


def embedding_units(text: str, operation: str) -> dict:
    """Единицы для эмбеддинга: только входные токены (оценка по символам)."""
    return {
        "operation": operation,
        "input_tokens": estimate_tokens(text),
        "output_tokens": 0,
    }


async def reserve_external_call(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    price: PriceSnapshot,
    units: dict,
) -> BillingContext:
    """Резервирует оценочную сумму внешнего вызова и фиксирует транзакцию.

    В отличие от чат-потока, где резерв коммитится вместе с сообщением, здесь
    у нас нет `messages`-записи: резервирование оформляется отдельной короткой
    транзакцией, чтобы не держать блокировку бюджета во время HTTP-вызова.
    """
    ctx = await check_and_reserve(
        session, user_id, price=price, estimated_units=units, message_id=None
    )
    await session.commit()
    return ctx


async def settle_external_call(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_profile_id: uuid.UUID,
    billing: BillingContext,
    usage: dict | None,
    estimated_units: dict | None = None,
) -> UsageRecord | None:
    """Фиксирует расход по внешнему вызову и закрывает резервирование.

    `estimated_units` — оценка для частично выполненного вызова (провайдер
    успел обработать только часть батчей и usage недоступен).
    """
    record = await finalize_generation(
        session,
        user_id=user_id,
        provider_id=provider_id,
        model_profile_id=model_profile_id,
        message_id=None,
        usage=usage,
        billing=billing,
        provider_request_id=None,
        estimated_units=estimated_units,
    )
    await session.commit()
    return record


async def cancel_external_call(
    session: AsyncSession, *, billing: BillingContext
) -> None:
    """Освобождает резервирование, если внешний вызов не состоялся."""
    await release_reservation(session, billing.reservation_id)
    await session.commit()
