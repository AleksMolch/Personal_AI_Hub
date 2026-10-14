"""Расчёт стоимости и оценка токенов.

Все денежные расчёты выполняются в Decimal (никогда float). Цены хранятся
за 1M токенов; стоимость вычисляется пропорционально фактическому числу
токенов. Оценка токенов — консервативная эвристика для резервирования.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from personal_hub.models import PriceSnapshot

TOKENS_PER_MILLION = Decimal(1_000_000)
_CENTS = Decimal("0.00000001")

# Эвристика: примерно 1 токен на 4 символа (для резервирования, не точный подсчёт).
CHARS_PER_TOKEN = 4
# Оценка выходных токенов, если лимит не задан.
DEFAULT_OUTPUT_TOKENS = 1024


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов по длине текста."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _money(value: Decimal) -> Decimal:
    """Квантует денежное значение до 8 знаков после запятой."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_cost(units: dict, price: PriceSnapshot) -> Decimal:
    """Вычисляет стоимость генерации по токенам и цене (за 1M токенов)."""
    input_tokens = Decimal(int(units.get("input_tokens", 0)))
    output_tokens = Decimal(int(units.get("output_tokens", 0)))
    cache_read = Decimal(int(units.get("cache_read_tokens", 0)))

    cost = (
        price.input_per_million * input_tokens
        + price.output_per_million * output_tokens
    ) / TOKENS_PER_MILLION

    if price.cache_read_per_million is not None:
        cost += price.cache_read_per_million * cache_read / TOKENS_PER_MILLION

    return _money(cost)


def estimate_cost(input_tokens: int, output_tokens: int, price: PriceSnapshot) -> Decimal:
    """Оценивает стоимость запроса до вызова (для резервирования)."""
    return compute_cost(
        {"input_tokens": input_tokens, "output_tokens": output_tokens}, price
    )


def parse_usage(usage: dict | None) -> dict:
    """Извлекает единицы (токены) из usage провайдера (OpenAI-compatible).

    Поддерживает prompt_tokens/completion_tokens, кэшированные токены и
    reasoning. Отсутствующие поля дают 0, а не ошибку.

    Токены рассуждений провайдеры отдают в двух разных местах: часть — плоским
    полем `reasoning_tokens`, OpenAI и OpenRouter — вложенно, в
    `completion_tokens_details.reasoning_tokens`. Читаем оба варианта, иначе
    показатель молча теряется, хотя он нужен UI для объяснения стоимости.

    Важно: reasoning_tokens НЕ добавляются к output_tokens. Провайдеры уже
    включают их в `completion_tokens`, поэтому прибавление привело бы к двойному
    списанию. Поле носит информационный характер.
    """
    if not usage:
        return {}
    units: dict[str, int] = {}
    if usage.get("prompt_tokens") is not None:
        units["input_tokens"] = int(usage["prompt_tokens"])
    if usage.get("completion_tokens") is not None:
        units["output_tokens"] = int(usage["completion_tokens"])

    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cache_read_input_tokens")
    if cached is not None:
        units["cache_read_tokens"] = int(cached)

    # Кэш на запись (Anthropic-style) приходит отдельным блоком.
    cache_creation = usage.get("cache_creation_input_tokens")
    if cache_creation is not None:
        units["cache_write_tokens"] = int(cache_creation)

    reasoning = usage.get("reasoning_tokens")
    if reasoning is None:
        completion_details = usage.get("completion_tokens_details") or {}
        reasoning = completion_details.get("reasoning_tokens")
    if reasoning is not None:
        units["reasoning_tokens"] = int(reasoning)
    return units
