"""Клиент сервиса headless-рендера страниц (ADR-0006).

Назначение: получить текст страницы после исполнения JavaScript. Обычный
HTTP-запрос видит только исходный HTML, а многие площадки дорисовывают таблицу
тарифов скриптами — тогда статический разбор находит ноль цен.

Место в архитектуре: модуль-клиент; сам браузер живёт в отдельном контейнере
`pricebot` (compose-профиль `pricebot`), чтобы Chromium не утяжелял образ API и
не исполнял чужой JavaScript в процессе, который владеет ключами.

Безопасность: URL проверяется тем же SSRF-фильтром, что и обычная загрузка, а
сам сервис рендера дополнительно ограничивает домены. Ошибки превращаются в
`PriceImportError` со стабильным кодом.
"""
from __future__ import annotations

import httpx

from personal_hub.pricing_import import (
    PriceImportError,
    _assert_public_url,
)


async def render_page(
    url: str,
    *,
    service_url: str,
    timeout_seconds: float = 30.0,
) -> str:
    """Просит сервис рендера вернуть текст страницы после исполнения JS.

    Args:
        url: Публичный адрес страницы тарифов.
        service_url: Базовый адрес сервиса `pricebot`.
        timeout_seconds: Таймаут запроса к сервису (рендер медленнее загрузки).

    Returns:
        Текст отрендеренной страницы.

    Raises:
        PriceImportError: При недопустимом адресе, недоступности сервиса,
            таймауте или ошибке рендера на стороне сервиса.
    """
    # Проверяем адрес и здесь: сервис рендера — отдельный процесс, и доверять
    # ему проверку пользовательского URL не стоит.
    _assert_public_url(url)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{service_url.rstrip('/')}/render",
                json={"url": url},
            )
    except httpx.TimeoutException as exc:
        raise PriceImportError(
            "PRICEBOT_TIMEOUT",
            "Сервис рендера не ответил вовремя: страница слишком тяжёлая.",
        ) from exc
    except httpx.RequestError as exc:
        raise PriceImportError(
            "PRICEBOT_UNREACHABLE",
            "Сервис рендера недоступен. Запустите его профилем `pricebot` "
            "или используйте обычный разбор.",
        ) from exc

    if response.status_code != 200:
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("error") or body.get("detail") or "")
        except ValueError:
            detail = ""
        message = "Сервис рендера не смог открыть страницу."
        if detail:
            message = f"{message} {detail}"
        raise PriceImportError("PRICEBOT_FAILED", f"{message} ({response.status_code})")

    try:
        body = response.json()
    except ValueError as exc:
        raise PriceImportError(
            "PRICEBOT_BAD_RESPONSE", "Сервис рендера вернул не JSON."
        ) from exc

    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise PriceImportError(
            "PRICEBOT_EMPTY",
            "Сервис рендера вернул пустую страницу: возможно, сайт показал "
            "заглушку вместо тарифов.",
        )
    return text
