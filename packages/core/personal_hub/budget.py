"""Доменные правила бюджетирования: исключения и вспомогательные типы.

Сам факт превышения бюджета — доменное событие с стабильным кодом. DB-операции
(резервирование, расчёт периода) вынесены в apps/api/app/billing.py.
"""
from __future__ import annotations

from enum import StrEnum


class BudgetPeriod(StrEnum):
    """Период, за который считается лимит."""

    DAILY = "daily"
    MONTHLY = "monthly"


class BudgetExceededError(Exception):
    """Запрос превысил hard limit бюджета. Код стабилен для UI."""

    def __init__(self, period: BudgetPeriod, limit: str, available: str) -> None:
        super().__init__(
            f"Превышен {period.value}-лимит: лимит {limit}, доступно {available}."
        )
        self.code = "BUDGET_EXCEEDED"
        self.period = period.value
        self.limit = limit
        self.available = available
