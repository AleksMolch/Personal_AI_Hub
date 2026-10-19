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
    """Вычисляет стоимость генерации по токенам и цене (за 1M токенов).

    Учитывает три оси тарификации, которые есть у многих провайдеров
    (например, DeepSeek): вход по цене cache miss, вход по цене cache hit и
    выход. Это принципиально для точности: `input_tokens` (prompt_tokens)
    ВКЛЮЧАЕТ кэшированные токены, поэтому начислять их и по цене входа, и по
    цене кэша нельзя — получается двойное списание.

    Правило:
    - если цена cache hit задана, кэшированные токены вычитаются из входных и
      оплачиваются по своей цене;
    - если цена cache hit НЕ задана, все входные токены идут по обычной цене
      (провайдер не сообщил отдельный тариф — не выдумываем скидку);
    - cache write (Anthropic-style) приходит отдельным полем и НЕ входит в
      prompt_tokens, поэтому начисляется дополнительно.

    Args:
        units: Токены из usage провайдера (`input_tokens`, `output_tokens`,
            `cache_read_tokens`, `cache_write_tokens`).
        price: Снимок цены модели.

    Returns:
        Стоимость, квантованная до 8 знаков.
    """
    input_tokens = Decimal(int(units.get("input_tokens", 0)))
    output_tokens = Decimal(int(units.get("output_tokens", 0)))
    cache_read = Decimal(int(units.get("cache_read_tokens", 0)))
    cache_write = Decimal(int(units.get("cache_write_tokens", 0)))

    # cache_read не может превысить вход: защита от противоречивого usage.
    cache_read = min(cache_read, input_tokens)
    billable_input = input_tokens

    cost = Decimal(0)
    if price.cache_read_per_million is not None and cache_read > 0:
        billable_input = input_tokens - cache_read
        cost += price.cache_read_per_million * cache_read / TOKENS_PER_MILLION

    cost += price.input_per_million * billable_input / TOKENS_PER_MILLION
    cost += price.output_per_million * output_tokens / TOKENS_PER_MILLION

    if price.cache_write_per_million is not None and cache_write > 0:
        cost += price.cache_write_per_million * cache_write / TOKENS_PER_MILLION

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
    if cached is None:
        # DeepSeek отдаёт попадания в кэш плоским полем
        # `prompt_cache_hit_tokens` (проверено по документации провайдера:
        # prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens).
        # Без этого фолбэка кэш-тариф не применялся бы вовсе.
        cached = usage.get("prompt_cache_hit_tokens")
    if cached is not None:
        units["cache_read_tokens"] = int(cached)

    # Промахи кэша: у DeepSeek это отдельное поле, равное остатку входа.
    # Храним для прозрачности расчёта; на стоимость влияет через input_tokens.
    cache_miss = usage.get("prompt_cache_miss_tokens")
    if cache_miss is not None:
        units["cache_miss_tokens"] = int(cache_miss)

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
