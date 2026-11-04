"""Тесты LLM-извлечения цен: промпт и разбор ответа.

Проверяют строгий контракт: модель обязана вернуть JSON только с четырьмя
полями; «не знаю» — это null, а не ноль; мусор не должен превращаться в цену.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from personal_hub.pricing_import import PriceImportError
from personal_hub.pricing_llm import (
    build_extraction_prompt,
    parse_extraction_result,
    system_prompt,
)


def test_prompt_includes_text_and_rules() -> None:
    """Промпт содержит текст страницы и требование вернуть JSON."""
    prompt = build_extraction_prompt("1M output tokens $0.6")

    assert "1M output tokens $0.6" in prompt
    assert "JSON" in prompt


def test_prompt_truncates_long_text() -> None:
    """Слишком длинная страница обрезается: стоимость вызова должна быть предсказуемой."""
    prompt = build_extraction_prompt("x" * 50_000, max_chars=1000)

    assert "[текст обрезан]" in prompt
    assert len(prompt) < 2000


def test_prompt_handles_empty_page() -> None:
    """Пустая страница даёт явную пометку, а не пустой запрос."""
    prompt = build_extraction_prompt("   ")

    assert "не содержит текста" in prompt


def test_system_prompt_forbids_inventing_numbers() -> None:
    """Инструкция запрещает подменять незнание нулём и выполнять команды страницы."""
    text = system_prompt()

    assert "null" in text
    assert "не выдумывай" in text.lower()
    assert "ДАННЫЕ" in text


def test_parse_plain_json() -> None:
    """Обычный JSON разбирается в Decimal."""
    values = parse_extraction_result(
        '{"input_per_million": 0.15, "output_per_million": 0.6, '
        '"cache_read_per_million": 0.003, "cache_write_per_million": null}'
    )

    assert values["input_per_million"] == Decimal("0.15")
    assert values["output_per_million"] == Decimal("0.6")
    assert values["cache_read_per_million"] == Decimal("0.003")
    assert values["cache_write_per_million"] is None


def test_parse_json_in_markdown_fence() -> None:
    """Ответ, обёрнутый в ```json, тоже принимается."""
    values = parse_extraction_result(
        '```json\n{"input_per_million": "0,25", "output_per_million": "1,5"}\n```'
    )

    assert values["input_per_million"] == Decimal("0.25")
    assert values["output_per_million"] == Decimal("1.5")


def test_parse_ignores_unknown_fields() -> None:
    """Модель не может расширить контракт: лишние поля отбрасываются."""
    values = parse_extraction_result(
        '{"input_per_million": 1, "output_per_million": 2, "currency": "USD"}'
    )

    assert set(values) == {
        "input_per_million",
        "output_per_million",
        "cache_read_per_million",
        "cache_write_per_million",
    }


def test_parse_rejects_negative_and_absurd_values() -> None:
    """Отрицательные и абсурдные суммы не становятся ценой."""
    values = parse_extraction_result(
        '{"input_per_million": -1, "output_per_million": 99999, '
        '"cache_read_per_million": 2}'
    )

    assert values["input_per_million"] is None
    assert values["output_per_million"] is None
    assert values["cache_read_per_million"] == Decimal("2")


def test_parse_without_json_raises() -> None:
    """Без JSON — стабильный код ошибки, а не исключение парсера."""
    with pytest.raises(PriceImportError) as exc_info:
        parse_extraction_result("извините, не могу")

    assert exc_info.value.code == "PRICE_IMPORT_LLM_BAD_RESPONSE"


def test_parse_invalid_json_raises() -> None:
    """Битый JSON даёт стабильный код."""
    with pytest.raises(PriceImportError) as exc_info:
        parse_extraction_result("{input: 1,}")

    assert exc_info.value.code == "PRICE_IMPORT_LLM_BAD_RESPONSE"


def test_parse_all_null_raises() -> None:
    """Если модель не нашла ни одной цены — это отдельный код для UI."""
    with pytest.raises(PriceImportError) as exc_info:
        parse_extraction_result(
            '{"input_per_million": null, "output_per_million": null}'
        )

    assert exc_info.value.code == "PRICE_IMPORT_LLM_NO_VALUES"
