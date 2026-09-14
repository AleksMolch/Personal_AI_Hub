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
    price = _price(cache_read="0.50")
    cost = compute_cost(
        {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 1_000_000},
        price,
    )
    assert cost == Decimal("1.50000000")


def test_compute_cost_no_cache_price() -> None:
    # Без цены на кэш кэшированные токены не учитываются.
    price = _price(cache_read=None)
    cost = compute_cost(
        {"input_tokens": 1_000_000, "cache_read_tokens": 1_000_000}, price
    )
    assert cost == Decimal("1.00000000")


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
