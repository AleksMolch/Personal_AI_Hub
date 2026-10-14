"""Backend веб-поиска через самостоятельно размещённый SearXNG.

Назначение: получать результаты веб-поиска из локального meta-поисковика без
внешних API-ключей и без передачи запросов третьим лицам сверх самих поисковых
движков.

Место в архитектуре: реализация `WebSearchProvider`. Вызывается из API перед
обращением к LLM, когда пользователь включил веб-доступ.

Требования к развёртыванию:
- SearXNG должен отдавать JSON: в `settings.yml` формат `json` нужно добавить в
  список `search.formats` (по умолчанию он выключен и запрос вернёт 403).
- Адрес задаётся `SEARXNG_URL` и является конфигурацией развёртывания, а не
  пользовательским вводом: URL не приходит из запроса и не может быть
  подменён на произвольный хост (защита от SSRF).
"""
from __future__ import annotations

import httpx

from personal_hub.websearch.base import (
    WebSearchError,
    WebSearchResponse,
    WebSearchResult,
)


class SearxngProvider:
    """Поиск через SearXNG JSON API.

    Attributes:
        base_url: Базовый адрес SearXNG.
        timeout_seconds: Таймаут запроса.
        engines: Необязательный список движков (пустой — выбор SearXNG).
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        engines: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.engines = engines or []

    async def search(self, query: str, *, limit: int) -> WebSearchResponse:
        """Выполняет поиск через `GET /search?format=json`.

        Args:
            query: Поисковый запрос.
            limit: Максимальное число результатов (передаётся SearXNG как
                ограничение страницы; срез делается и на нашей стороне).

        Returns:
            Нормализованный ответ с результатами и замечаниями.

        Raises:
            WebSearchError: `WEB_SEARCH_FORBIDDEN` при 403 (JSON выключен),
                `WEB_SEARCH_TIMEOUT` при таймауте, `WEB_SEARCH_UNREACHABLE`
                при сетевом сбое, `WEB_SEARCH_BAD_RESPONSE` при неверном JSON.
        """
        params: dict[str, str] = {"q": query, "format": "json"}
        if self.engines:
            params["engines"] = ",".join(self.engines)

        url = f"{self.base_url}/search"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise WebSearchError(
                "WEB_SEARCH_TIMEOUT", "Поиск не ответил вовремя.", True
            ) from exc
        except httpx.RequestError as exc:
            raise WebSearchError(
                "WEB_SEARCH_UNREACHABLE", "Поисковый сервис недоступен.", True
            ) from exc

        if resp.status_code == 403:
            # Самая частая причина: формат json не добавлен в search.formats.
            raise WebSearchError(
                "WEB_SEARCH_FORBIDDEN",
                "Поисковый сервис отклонил запрос: формат JSON не включён "
                "(search.formats в settings.yml).",
            )
        if resp.status_code != 200:
            raise WebSearchError(
                "WEB_SEARCH_FAILED",
                f"Поисковый сервис вернул код {resp.status_code}.",
                resp.status_code >= 500,
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise WebSearchError(
                "WEB_SEARCH_BAD_RESPONSE",
                "Поисковый сервис вернул ответ не в формате JSON.",
            ) from exc

        results: list[WebSearchResult] = []
        for item in (body.get("results") or [])[:limit]:
            url_value = item.get("url")
            if not url_value:
                # Запись без адреса бесполезна для цитаты: пропускаем, а не
                # показываем пользователю битую ссылку.
                continue
            results.append(
                WebSearchResult(
                    title=item.get("title") or url_value,
                    url=url_value,
                    snippet=item.get("content") or "",
                    engine=item.get("engine") or "",
                )
            )

        warnings: list[str] = []
        unresponsive = body.get("unresponsive_engines") or []
        if unresponsive:
            names = ", ".join(
                str(engine[0]) if isinstance(engine, (list, tuple)) else str(engine)
                for engine in unresponsive
            )
            # Часть движков может быть недоступна: это не ошибка, но
            # пользователь должен знать, что выдача неполная.
            warnings.append(f"Часть поисковых движков не ответила: {names}.")

        return WebSearchResponse(query=query, results=results, warnings=warnings)
