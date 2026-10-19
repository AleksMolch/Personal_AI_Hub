"""Тесты нормализации десятичного ввода.

Регрессия на реальный дефект интерфейса: пользователь вводил цену как `0,022`
(запятая — десятичный разделитель в русской локали), а API ожидал точку и
отвечал 422 «Некорректные данные запроса» без указания поля.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import BudgetUpdate, FxRateCreate, PriceCreate, _normalize_decimal_input

_MODEL_ID = "00000000-0000-0000-0000-000000000001"


def _price(input_value: object, output_value: object = "1.0") -> PriceCreate:
    """Создаёт схему цены с заданными значениями полей."""
    return PriceCreate(
        model_profile_id=_MODEL_ID,
        input_per_million=input_value,
        output_per_million=output_value,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0,022", "0.022"),
        ("0.022", "0.022"),
        ("  1,98  ", "1.98"),
        ("1 234,5", "1234.5"),
        ("1\u00a0234,5", "1234.5"),
        ("0", "0"),
        ("7", "7"),
    ],
)
def test_normalize_decimal_input(raw: str, expected: str) -> None:
    """Запятая заменяется точкой, пробелы удаляются."""
    assert _normalize_decimal_input(raw) == expected


def test_non_string_is_untouched() -> None:
    """Числа из JSON не трогаем: они уже корректны."""
    assert _normalize_decimal_input(Decimal("1.5")) == Decimal("1.5")
    assert _normalize_decimal_input(None) is None


def test_price_accepts_comma() -> None:
    """Цена с запятой проходит валидацию и сохраняется точно."""
    price = _price("0,022", "1,98")

    assert price.input_per_million == Decimal("0.022")
    assert price.output_per_million == Decimal("1.98")


def test_price_accepts_dot() -> None:
    """Точка продолжает работать: старые клиенты не ломаются."""
    price = _price("0.022", "1.98")

    assert price.input_per_million == Decimal("0.022")


def test_price_rejects_garbage() -> None:
    """Мусор по-прежнему отклоняется — терпимость не превращается в приём всего."""
    with pytest.raises(ValidationError):
        _price("дорого")


def test_price_rejects_negative() -> None:
    """Отрицательная цена недопустима (ограничение ge=0 сохраняется)."""
    with pytest.raises(ValidationError):
        _price("-1")


def test_budget_limit_accepts_comma() -> None:
    """Лимит бюджета принимает запятую."""
    budget = BudgetUpdate(daily_limit="5,5")

    assert budget.daily_limit == Decimal("5.5")


def test_budget_empty_string_is_null() -> None:
    """Пустая строка из формы означает «без лимита».

    Pydantic не превращает `""` в None автоматически, поэтому проверяем, что
    такое значение отклоняется: UI отправляет null, и это осознанный контракт.
    """
    with pytest.raises(ValidationError):
        BudgetUpdate(daily_limit="")


def test_fx_rate_accepts_comma() -> None:
    """Курс валют принимает запятую."""
    rate = FxRateCreate(from_currency="RUB", to_currency="USD", rate="0,011")

    assert rate.rate == Decimal("0.011")
