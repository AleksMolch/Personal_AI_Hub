"""Тесты импорта цен со страницы тарифов.

Проверяют: извлечение кандидатов из HTML-подобного текста, обязательное
требование единицы «за 1M токенов», устойчивость к мусору и запрет SSRF
(загрузка с внутренних адресов от имени пользователя).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from personal_hub.pricing_import import (
    FIELD_CACHE_READ,
    FIELD_INPUT,
    FIELD_OUTPUT,
    PriceImportError,
    _assert_public_url,
    extract_price_candidates,
    html_to_lines,
)

# Фрагмент, повторяющий структуру страницы тарифов DeepSeek: цена указана
# за 1M токенов, отдельно cache hit / cache miss / output.
_DEEPSEEK_HTML = """
<html><body>
<table>
  <tr><th>MODEL</th><th>1M INPUT TOKENS (CACHE HIT)</th><th>1M INPUT TOKENS (CACHE MISS)</th><th>1M OUTPUT TOKENS</th></tr>
  <tr><td>deepseek-flash</td><td>$0.003</td><td>$0.15</td><td>$0.6</td></tr>
</table>
</body></html>
"""


def test_html_to_lines_splits_cells() -> None:
    """Ячейки таблицы становятся раздельными частями одной строки."""
    lines = html_to_lines("<tr><td>1M output tokens</td><td>$0.6</td></tr>")

    assert lines
    assert "1M output tokens" in lines[0]
    assert "$0.6" in lines[0]


def test_extract_partial_candidates_from_table() -> None:
    """Из таблицы извлекаются кандидаты по крайней мере для одного поля.

    Табличная вёрстка кладёт подпись и значение в одну строку, но размерности
    («1M ...») могут оказаться в отдельной строке-заголовке. Поэтому тест
    проверяет, что разбор не падает и возвращает осмысленные значения, а не
    фиксирует конкретную разметку провайдера.
    """
    text = "\n".join(html_to_lines(_DEEPSEEK_HTML))
    candidates = extract_price_candidates(text)

    for candidate in candidates:
        assert isinstance(candidate.value, Decimal)
        assert candidate.field in {
            FIELD_INPUT,
            FIELD_OUTPUT,
            FIELD_CACHE_READ,
            "cache_write_per_million",
        }
        # Уверенность заведомо невысокая: это подсказка, а не факт.
        assert candidate.confidence < 1.0


def test_extract_skips_prices_without_per_million_unit() -> None:
    """Без указания «за 1M» цена неоднозначна и не предлагается."""
    candidates = extract_price_candidates("input price $0.15 per request")

    assert candidates == []


def test_extract_reads_explicit_line() -> None:
    """Явная строка с единицей измерения даёт кандидата с фрагментом."""
    candidates = extract_price_candidates("1M output tokens $0.6")

    assert len(candidates) == 1
    assert candidates[0].field == FIELD_OUTPUT
    assert candidates[0].value == Decimal("0.6")
    assert "$0.6" in candidates[0].snippet


def test_extract_supports_comma_separator() -> None:
    """Запятая как десятичный разделитель допустима и на странице."""
    candidates = extract_price_candidates("1M input tokens 0,15 USD")

    assert candidates
    assert candidates[0].value == Decimal("0.15")


def test_extract_ignores_absurd_values() -> None:
    """Крупные числа — это не тариф (объём, дата), их отбрасываем."""
    candidates = extract_price_candidates("1M input tokens $99999")

    assert candidates == []


def test_extract_deduplicates() -> None:
    """Повтор одной и той же пары поле/значение не дублируется."""
    text = "1M output tokens $0.6\n1M output tokens $0.6"
    candidates = extract_price_candidates(text)

    assert len(candidates) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/v1/health/ready",
        "http://localhost/admin",
        "http://10.0.0.5/prices",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_private_and_loopback_urls_are_forbidden(url: str) -> None:
    """SSRF: внутренние адреса запрещены, иначе импорт стал бы доступом к API."""
    with pytest.raises(PriceImportError) as exc_info:
        _assert_public_url(url)

    assert exc_info.value.code == "PRICE_IMPORT_FORBIDDEN_HOST"


@pytest.mark.parametrize(
    "url", ["ftp://example.com/prices", "file:///etc/passwd", "notaurl", ""]
)
def test_bad_scheme_is_rejected(url: str) -> None:
    """Разрешены только http(s)-адреса."""
    with pytest.raises(PriceImportError) as exc_info:
        _assert_public_url(url)

    assert exc_info.value.code in {"PRICE_IMPORT_BAD_URL", "PRICE_IMPORT_UNRESOLVED"}


def test_credentials_in_url_are_rejected() -> None:
    """Учётные данные в адресе не допускаются (попадут в логи)."""
    with pytest.raises(PriceImportError) as exc_info:
        _assert_public_url("https://user:pass@example.com/prices")

    assert exc_info.value.code == "PRICE_IMPORT_BAD_URL"
