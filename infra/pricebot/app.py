"""Минимальный сервис headless-рендера страниц (ADR-0006).

Назначение: открыть пользовательскую страницу в настоящем браузере и вернуть её
текст после исполнения JavaScript. Нужен для страниц тарифов, где цены
дорисовываются скриптами: обычный HTTP-запрос видит только пустую оболочку.

Место в архитектуре: отдельный контейнер `pricebot` (compose-профиль
`pricebot`). API обращается к нему по внутренней сети, когда обычный разбор не
нашёл цен. Chromium намеренно не живёт в образе API: он тяжёлый, исполняет
чужой JavaScript и не должен соседствовать с процессом, владеющим ключами.

Безопасность:
- адрес проверяется тем же SSRF-правилом, что и обычная загрузка;
- все запросы страницы перехватываются: разрешены только тот же домен и
  служебные схемы (`data:`, `blob:`, `about:`), остальное блокируется;
- каждый запуск — свежий контекст без кук и сохранённого состояния;
- ограничены время рендера и длина возвращаемого текста.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from personal_hub.pricing_import import PriceImportError, assert_public_url
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

# Сколько ждём загрузку страницы. Переопределяется переменной окружения.
_TIMEOUT_MS = int(os.environ.get("PRICEBOT_TIMEOUT_MS", "25000"))
# Верхняя граница текста: страницы бывают огромными, а нам нужен только прайс.
_MAX_TEXT_CHARS = 200_000
# Представляемся обычным браузером: headless-UA часто блокируется сайтами.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# Одновременно рендерим одну страницу: Chromium прожорлив по памяти.
_render_lock = asyncio.Semaphore(1)

app = FastAPI(title="Personal AI Hub pricebot", version="0.1.0")


class RenderRequest(BaseModel):
    """Запрос рендера страницы."""

    url: str = Field(min_length=8, max_length=2048)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Проверка живости сервиса."""
    return {"status": "ok"}


def _same_origin_allowed(request_url: str, target_host: str | None) -> bool:
    """Решает, разрешать ли запрос страницы.

    Args:
        request_url: Адрес ресурса, который запрашивает браузер.
        target_host: Хост открываемой страницы.

    Returns:
        True, если ресурс служебный или принадлежит тому же хосту.
    """
    parsed = urlparse(request_url)
    if parsed.scheme in ("data", "blob", "about"):
        return True
    return bool(target_host) and parsed.hostname == target_host


@app.post("/render")
async def render(payload: RenderRequest) -> dict[str, str]:
    """Открывает страницу в Chromium и возвращает её текст.

    Args:
        payload: Адрес страницы.

    Returns:
        Словарь с текстом страницы.

    Raises:
        HTTPException: 400 при недопустимом адресе, 502 при сбое браузера,
            504 при таймауте загрузки.
    """
    try:
        assert_public_url(payload.url)
    except PriceImportError as exc:
        raise HTTPException(400, f"{exc.message} ({exc.code})") from exc

    target_host = urlparse(payload.url).hostname
    async with _render_lock:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                # --no-sandbox нужен в контейнере без privileged-режима.
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1200},
                    user_agent=_USER_AGENT,
                )

                async def _guard(route):
                    if _same_origin_allowed(route.request.url, target_host):
                        await route.continue_()
                    else:
                        # Сторонние домены (аналитика, реклама, трекеры) не
                        # нужны для тарифов и создают лишние исходящие запросы.
                        await route.abort()

                await context.route("**/*", _guard)
                page = await context.new_page()
                try:
                    await page.goto(
                        payload.url, wait_until="networkidle", timeout=_TIMEOUT_MS
                    )
                except Exception as exc:  # таймаут или навигационная ошибка
                    if "Timeout" in type(exc).__name__ or "timeout" in str(exc).lower():
                        raise HTTPException(
                            504,
                            "Страница не загрузилась за отведённое время "
                            "(возможна защита от ботов).",
                        ) from exc
                    raise HTTPException(502, "Не удалось открыть страницу.") from exc

                # Прокрутка провоцирует подгрузку таблиц с ленивой отрисовкой.
                for _ in range(3):
                    await page.mouse.wheel(0, 2000)
                    await page.wait_for_timeout(250)

                text = await page.inner_text("body")
                return {"text": text[:_MAX_TEXT_CHARS], "url": payload.url}
            finally:
                await browser.close()
