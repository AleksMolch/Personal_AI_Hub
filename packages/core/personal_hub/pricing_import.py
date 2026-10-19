"""Извлечение цен со страницы тарифов провайдера (кандидаты, не истина).

Назначение: помочь заполнить цены модели, когда провайдер не отдаёт их через
API (например, DeepSeek в `/models` возвращает только идентификаторы). Модуль
НЕ сохраняет ничего сам: он возвращает найденные значения как кандидатов с
фрагментами текста, а пользователь обязан их проверить и подтвердить.

Место в архитектуре: вспомогательный сервис рядом с провайдерами. Используется
эндпоинтом `POST /api/v1/prices/extract`; сохранение цены остаётся в обычном
`POST /api/v1/prices` с источником `url`.

Почему эвристики, а не «полный автомат»:
- у провайдеров нет машинно-читаемого контракта на страницу тарифов;
- разметка меняется, поэтому любое значение может оказаться не тем;
- ошибка в цене искажает учёт расходов, а это дороже ручной проверки.
Поэтому результат всегда помечается как требующий подтверждения.

Безопасность (SSRF): адрес приходит от пользователя, но загружать можно только
публичные http(s)-адреса. Приватные, loopback и link-local диапазоны
запрещены, редиректы не выполняются, размер ответа ограничен.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx

MAX_PAGE_BYTES = 512 * 1024
FETCH_TIMEOUT_SECONDS = 12.0

# Поля цены, которые умеет заполнять импорт.
FIELD_INPUT = "input_per_million"
FIELD_OUTPUT = "output_per_million"
FIELD_CACHE_READ = "cache_read_per_million"
FIELD_CACHE_WRITE = "cache_write_per_million"

# Ключевые слова для определения поля. Порядок важен: сначала более
# специфичные (cache hit/write), иначе строка про кэш была бы принята за вход.
_FIELD_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FIELD_CACHE_WRITE, ("cache write", "cache_write", "запись в кэш")),
    (FIELD_CACHE_READ, ("cache hit", "cache_read", "cache read", "попадан")),
    (FIELD_OUTPUT, ("output", "completion", "выход", "генерац")),
    (FIELD_INPUT, ("cache miss", "input", "prompt", "вход")),
)

# Денежное значение: $0.003, $ 0,022, 0.15 USD.
_MONEY_RE = re.compile(
    r"(?:\$\s*(?P<d1>\d+(?:[.,]\d+)?))"
    r"|(?:(?P<d2>\d+(?:[.,]\d+)?)\s*(?:\$|usd|USD))"
)


@dataclass(frozen=True)
class PriceCandidate:
    """Найденное на странице значение цены.

    Attributes:
        field: Имя поля цены модели.
        value: Значение в валюте страницы (за 1M токенов, как у провайдеров).
        snippet: Фрагмент текста, на основании которого сделана догадка.
        confidence: Грубая оценка уверенности 0..1 (эвристика, не гарантия).
    """

    field: str
    value: Decimal
    snippet: str
    confidence: float


class PriceImportError(Exception):
    """Ошибка загрузки страницы со стабильным кодом.

    Attributes:
        code: Стабильный код для UI и логов.
        message: Понятное пользователю описание.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _assert_public_url(url: str) -> None:
    """Проверяет, что URL публичный и загрузка не станет SSRF.

    Args:
        url: Адрес страницы тарифов.

    Raises:
        PriceImportError: Если схема не http(s), адрес указывает на приватную
            сеть или содержит учётные данные.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PriceImportError(
            "PRICE_IMPORT_BAD_URL", "Адрес должен начинаться с http:// или https://."
        )
    if not parsed.hostname:
        raise PriceImportError("PRICE_IMPORT_BAD_URL", "В адресе нет имени хоста.")
    if parsed.username or parsed.password:
        raise PriceImportError(
            "PRICE_IMPORT_BAD_URL", "Адрес не должен содержать логин и пароль."
        )

    try:
        addresses = {
            info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)
        }
    except OSError as exc:
        raise PriceImportError(
            "PRICE_IMPORT_UNRESOLVED", f"Не удалось разрешить имя {parsed.hostname}."
        ) from exc

    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            # Запрет приватных диапазонов закрывает попытку обратиться к
            # внутренним сервисам (postgres, qdrant, api) через импорт.
            raise PriceImportError(
                "PRICE_IMPORT_FORBIDDEN_HOST",
                "Загрузка с внутренних адресов запрещена.",
            )


async def fetch_pricing_page(url: str) -> str:
    """Загружает страницу тарифов и возвращает её текст.

    Редиректы обрабатываются вручную (до трёх переходов), и каждый новый адрес
    повторно проходит проверку SSRF: иначе публичная страница могла бы увести
    запрос на внутренний сервис.

    Args:
        url: Публичный http(s)-адрес страницы.

    Returns:
        HTML страницы (обрезанный до `MAX_PAGE_BYTES`).

    Raises:
        PriceImportError: При недопустимом адресе, таймауте, ошибке сети,
            слишком большом числе редиректов или слишком большом ответе.
    """
    current = url
    for _ in range(4):
        _assert_public_url(current)
        try:
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET",
                    current,
                    headers={"User-Agent": "PersonalAIHub/0.1 price-import"},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise PriceImportError(
                                "PRICE_IMPORT_REDIRECT",
                                "Страница перенаправляет, но адрес не указан.",
                            )
                        # Относительный Location приводим к абсолютному.
                        current = str(httpx.URL(current).join(location))
                        continue
                    if response.status_code != 200:
                        raise PriceImportError(
                            "PRICE_IMPORT_HTTP_ERROR",
                            f"Страница вернула код {response.status_code}.",
                        )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PAGE_BYTES:
                            raise PriceImportError(
                                "PRICE_IMPORT_TOO_LARGE",
                                "Страница слишком большая для разбора.",
                            )
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="replace")
        except httpx.TimeoutException as exc:
            raise PriceImportError(
                "PRICE_IMPORT_TIMEOUT", "Сайт провайдера не ответил вовремя."
            ) from exc
        except httpx.RequestError as exc:
            raise PriceImportError(
                "PRICE_IMPORT_UNREACHABLE", "Не удалось загрузить страницу."
            ) from exc

    raise PriceImportError(
        "PRICE_IMPORT_REDIRECT",
        "Слишком много перенаправлений. Укажите конечный URL тарифов.",
    )


def html_to_lines(html: str) -> list[str]:
    """Превращает HTML в список текстовых строк.

    Args:
        html: Исходная разметка страницы.

    Returns:
        Строки без тегов; таблицы разбиваются по ячейкам через разделитель `|`,
        чтобы цена и её подпись оказывались в одной строке.
    """
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    with_cells = re.sub(
        r"</(td|th)>", " | ", without_scripts, flags=re.IGNORECASE
    )
    with_breaks = re.sub(
        r"</(tr|p|div|li|h[1-6]|table|section)>", "\n", with_cells, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", " ", with_breaks)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = []
    for raw in text.splitlines():
        normalized = re.sub(r"\s+", " ", raw).strip()
        if normalized:
            lines.append(normalized)
    return lines


def _parse_money(value: str) -> Decimal | None:
    """Преобразует денежную строку в Decimal (запятая допустима)."""
    try:
        return Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _detect_field(line: str) -> str | None:
    """Определяет поле цены по ключевым словам строки."""
    lowered = line.lower()
    for field, keywords in _FIELD_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return field
    return None


def extract_price_candidates(text: str, *, max_candidates: int = 12) -> list[PriceCandidate]:
    """Ищет в тексте страницы кандидатов на цены модели.

    Значения трактуются как цена за 1M токенов — именно так публикуют тарифы
    проверенные провайдеры. Если строка содержит несколько сумм, возвращаются
    все: выбрать правильную должен пользователь.

    Args:
        text: Текст страницы (обычно результат `html_to_lines`, склеенный).
        max_candidates: Верхний предел числа кандидатов.

    Returns:
        Список кандидатов; пустой список означает «ничего достоверного не нашли».
    """
    candidates: list[PriceCandidate] = []
    seen: set[tuple[str, Decimal]] = set()

    for line in text.splitlines():
        field = _detect_field(line)
        if field is None:
            continue
        if "1m" not in line.lower() and "1 m" not in line.lower() and "million" not in line.lower():
            # Цены без указания единицы измерения слишком неоднозначны:
            # за токен, за 1K или за 1M — разница в тысячу раз.
            continue
        for match in _MONEY_RE.finditer(line):
            raw = match.group("d1") or match.group("d2")
            if not raw:
                continue
            value = _parse_money(raw)
            if value is None or value > Decimal("10000"):
                # Абсурдно большие суммы — это не тариф, а объём или дата.
                continue
            key = (field, value)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                PriceCandidate(
                    field=field,
                    value=value,
                    snippet=line[:240],
                    # Уверенность невысокая по определению: разбор
                    # эвристический и требует сверки пользователем.
                    confidence=0.4,
                )
            )
            if len(candidates) >= max_candidates:
                return candidates
    return candidates
