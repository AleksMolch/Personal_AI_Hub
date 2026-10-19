"""Тесты расчёта стоимости (Decimal) и оценки токенов.

Граничные случаи: ноль токенов, дробные цены, кэшированные токены.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from personal_hub.costs import compute_cost, estimate_cost, estimate_tokens, parse_usage
from personal_hub.models import PriceSnapshot


def _price(
    input_per_million: str = "1.00",
    output_per_million: str = "2.00",
    cache_read: str | None = "0.50",
) -> PriceSnapshot:
    return PriceSnapshot(
        model_profile_id=uuid.uuid4(),
        currency="USD",
        input_per_million=Decimal(input_per_million),
        output_per_million=Decimal(output_per_million),
        cache_read_per_million=Decimal(cache_read) if cache_read else None,
    )


def test_compute_cost_basic() -> None:
    # 1M входных по $1 + 1M выходных по $2 = $3.
    cost = compute_cost(
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000}, _price()
    )
    assert cost == Decimal("3.00000000")


def test_compute_cost_fractional() -> None:
    # 1000 входных = $0.001; 500 выходных = $0.001 → $0.002.
    cost = compute_cost({"input_tokens": 1000, "output_tokens": 500}, _price())
    assert cost == Decimal("0.00200000")


def test_compute_cost_zero_tokens() -> None:
    assert compute_cost({}, _price()) == Decimal("0.00000000")


def test_compute_cost_with_cache_read() -> None:
    """Кэшированные токены НЕ оплачиваются дважды.

    `input_tokens` (prompt_tokens) включает попадания в кэш, поэтому при
    известной цене cache hit из входа вычитается: 1M входа, из них 1M в кэше →
    платим только за кэш, а не за вход плюс кэш.
    """
    price = _price(input_per_million="1.00", cache_read="0.50")
    cost = compute_cost(
        {
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_tokens": 1_000_000,
        },
        price,
    )
    assert cost == Decimal("0.50000000")


def test_compute_cost_partial_cache_hit() -> None:
    """Частичное попадание: промахи по цене входа, попадания по цене кэша.

    800k из 1M в кэше: 200k × $1 + 800k × $0.5 = $0.6.
    """
    price = _price(input_per_million="1.00", output_per_million="0", cache_read="0.50")
    cost = compute_cost(
        {
            "input_tokens": 1_000_000,
            "cache_read_tokens": 800_000,
            "output_tokens": 0,
        },
        price,
    )
    assert cost == Decimal("0.60000000")


def test_compute_cost_cache_without_price_uses_input_rate() -> None:
    """Без цены cache hit весь вход оплачивается по обычной цене.

    Скидку не выдумываем: если провайдер не сообщил кэш-тариф, вход стоит
    столько же, сколько обычно.
    """
    price = _price(input_per_million="1.00", cache_read=None)
    cost = compute_cost(
        {"input_tokens": 1_000_000, "cache_read_tokens": 1_000_000}, price
    )
    assert cost == Decimal("1.00000000")


def test_compute_cost_cache_read_cannot_exceed_input() -> None:
    """Противоречивый usage не даёт отрицательного входа."""
    price = _price(input_per_million="1.00", cache_read="0.50")
    cost = compute_cost(
        {"input_tokens": 1000, "cache_read_tokens": 5000}, price
    )
    # Все 1000 токенов ушли в кэш: 1000 × $0.5 / 1M.
    assert cost == Decimal("0.00050000")


def test_compute_cost_cache_write_is_added() -> None:
    """Cache write (Anthropic-style) не входит во вход и начисляется отдельно."""
    price = PriceSnapshot(
        model_profile_id=uuid.uuid4(),
        currency="USD",
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("0"),
        cache_read_per_million=Decimal("0.50"),
        cache_write_per_million=Decimal("2.00"),
    )
    cost = compute_cost(
        {"input_tokens": 1000, "output_tokens": 0, "cache_write_tokens": 1_000_000},
        price,
    )
    # 1000 входных × $1 / 1M + 1M записи в кэш × $2 / 1M.
    assert cost == Decimal("2.00100000")


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 40) == 10


def test_estimate_cost_uses_output_tokens() -> None:
    cost = estimate_cost(1000, 2000, _price())
    assert cost == Decimal("0.00500000")


def test_parse_usage_full() -> None:
    units = parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 30},
        }
    )
    assert units == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_tokens": 30,
    }


def test_parse_usage_empty() -> None:
    assert parse_usage(None) == {}
    assert parse_usage({}) == {}


def test_parse_usage_deepseek_cache_fields() -> None:
    """DeepSeek отдаёт попадания и промахи кэша плоскими полями.

    Подтверждено документацией провайдера:
    prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens.
    Без чтения этих полей кэш-тариф не применялся бы вовсе.
    """
    units = parse_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens_details": {"reasoning_tokens": 40},
        }
    )

    assert units["input_tokens"] == 1000
    assert units["cache_read_tokens"] == 800
    assert units["cache_miss_tokens"] == 200
    assert units["reasoning_tokens"] == 40


def test_deepseek_usage_cost_is_not_double_counted() -> None:
    """Сквозной расчёт на реальной форме usage DeepSeek.

    1000 входных, из них 800 в кэше; 100 выходных. Цены DeepSeek Flash
    (off-peak): cache hit $0.003, cache miss $0.15, output $0.6 за 1M.
    Ожидаем 200×0.15 + 800×0.003 + 100×0.6 = 30 + 2.4 + 60 = 92.4 → /1M.
    """
    price = PriceSnapshot(
        model_profile_id=uuid.uuid4(),
        currency="USD",
        input_per_million=Decimal("0.15"),
        output_per_million=Decimal("0.6"),
        cache_read_per_million=Decimal("0.003"),
    )
    units = parse_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
        }
    )

    cost = compute_cost(units, price)

    assert cost == Decimal("0.00009240")
