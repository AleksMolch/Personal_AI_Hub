"""Универсальный OpenAI-compatible адаптер.

Обслуживает OpenRouter, RouterAI, Selectel и любой OpenAI-compatible endpoint:
все они принимают Bearer-ключ и GET /models. Специфические отличия (если
возникнут) выносятся в отдельные адаптеры, а не в условные ветки.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal, InvalidOperation

import httpx

from personal_hub.providers.base import (
    Capability,
    ChatChunk,
    ChatCompletionResult,
    ChatRequest,
    EmbeddingResult,
    HealthResult,
    ProviderConnection,
    RemoteModel,
    RemotePricing,
)
from personal_hub.providers.errors import ProviderError, normalize_http_status

DEFAULT_TIMEOUT_SECONDS = 15.0
STREAM_READ_TIMEOUT_SECONDS = 180.0

# OpenRouter-style pricing отдаёт цену за токен; PriceSnapshot хранит за 1M.
_TOKENS_PER_MILLION = Decimal("1000000")

# Типы провайдеров, у которых управление рассуждениями принимается в
# нормализованном объекте `reasoning`, а не в плоском `reasoning_effort`.
# Оба поля документированы OpenRouter; отправляем ровно одно, потому что
# порядок разрешения конфликта при отправке обоих не документирован.
_REASONING_OBJECT_PROVIDERS = frozenset({"openrouter"})

# Значения `capabilities`/`supported_parameters`, по которым провайдер сообщает
# о поддержке управления рассуждениями.
_REASONING_MARKERS = frozenset({"reasoning", "reasoning_effort", "include_reasoning"})

# Понятные сообщения для пользователя по нормализованному коду.
_MESSAGES: dict[str, str] = {
    "PROVIDER_UNAUTHORIZED": "Неверный API-ключ (401).",
    "PROVIDER_INSUFFICIENT_BALANCE": "Недостаточно средств (402).",
    "PROVIDER_FORBIDDEN": "Доступ запрещён (403).",
    "PROVIDER_RATE_LIMITED": "Провайдер временно ограничил частоту запросов (429).",
    "PROVIDER_ERROR": "Ошибка провайдера.",
}


def _declares_reasoning(item: dict) -> bool:
    """Определяет поддержку управления рассуждениями по данным провайдера.

    Признак берётся только из явных деклараций в ответе `/models`:
    `supported_parameters` (OpenRouter) или `capabilities`. Мы намеренно НЕ
    угадываем по названию модели: правила проекта запрещают выводить поддержку
    возможности из маркетингового имени, а ошибка здесь приводит к 400 у
    провайдера или к декоративному селектору в UI.

    Args:
        item: Элемент списка моделей из ответа провайдера.

    Returns:
        True, если провайдер явно заявил поддержку управления рассуждениями.
    """
    params = item.get("supported_parameters")
    if isinstance(params, list) and _REASONING_MARKERS.intersection(params):
        return True
    caps = item.get("capabilities")
    if isinstance(caps, list) and _REASONING_MARKERS.intersection(caps):
        return True
    return False


def _parse_pricing(item: dict) -> RemotePricing | None:
    """Извлекает цену модели из OpenRouter-style `pricing` (за токен → за 1M).

    Возвращает None, если цены нет или она нечисловая (безопасно игнорируем,
    чтобы синхронизация не падала на неожиданном формате провайдера).
    """
    pricing = item.get("pricing")
    if not isinstance(pricing, dict):
        return None
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    if prompt is None or completion is None:
        return None
    try:
        input_pm = Decimal(str(prompt)) * _TOKENS_PER_MILLION
        output_pm = Decimal(str(completion)) * _TOKENS_PER_MILLION
    except (InvalidOperation, TypeError, ValueError):
        return None
    cache_read = pricing.get("cache_read")
    cache_write = pricing.get("cache_write")
    return RemotePricing(
        input_per_million=input_pm,
        output_per_million=output_pm,
        cache_read_per_million=_to_per_million(cache_read),
        cache_write_per_million=_to_per_million(cache_write),
    )


def _to_per_million(value: object) -> Decimal | None:
    """Преобразует per-token значение в per-million; None для нечислового."""
    if value is None:
        return None
    try:
        return Decimal(str(value)) * _TOKENS_PER_MILLION
    except (InvalidOperation, TypeError, ValueError):
        return None


class OpenAICompatibleAdapter:
    """Реализует health, list_models и чат для OpenAI-compatible API."""

    def _headers(self, connection: ProviderConnection) -> dict[str, str]:
        return {"Authorization": f"Bearer {connection.api_key}"}

    def _apply_reasoning(
        self, payload: dict, connection: ProviderConnection, request: ChatRequest
    ) -> None:
        """Добавляет в тело запроса управление глубиной рассуждений.

        Поле кладётся только если модель объявила capability `reasoning`:
        отправка параметра модели без поддержки приводит к 400 у части
        провайдеров, а «на всякий случай» слать его нельзя.

        Форма поля зависит от типа провайдера и берётся из данных провайдера, а
        не из названия модели: OpenRouter принимает объект `reasoning.effort`,
        остальные OpenAI-compatible endpoints — плоский `reasoning_effort`.

        Args:
            payload: Тело запроса, которое будет отправлено (изменяется на месте).
            connection: Соединение с провайдером (определяет форму поля).
            request: Запрос; используется глубина и capabilities модели.
        """
        depth = request.reasoning_depth
        if depth is None:
            return
        if Capability.REASONING.value not in request.model_capabilities:
            return
        if connection.provider_type in _REASONING_OBJECT_PROVIDERS:
            payload["reasoning"] = {"effort": depth.value}
        else:
            payload["reasoning_effort"] = depth.value

    async def health(self, connection: ProviderConnection) -> HealthResult:
        """Проверяет ключ запросом GET /models (без платных вызовов)."""
        url = f"{connection.base_url.rstrip('/')}/models"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=self._headers(connection))
        except httpx.TimeoutException:
            return HealthResult(ok=False, message="Таймаут соединения с провайдером.")
        except httpx.RequestError:
            return HealthResult(ok=False, message="Не удалось подключиться к провайдеру.")

        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            count = len(resp.json().get("data", []))
            return HealthResult(
                ok=True,
                message="Соединение успешно.",
                latency_ms=latency_ms,
                model_count=count,
            )
        err = normalize_http_status(resp.status_code)
        return HealthResult(
            ok=False,
            message=_MESSAGES.get(err.code, err.message),
            latency_ms=latency_ms,
        )

    async def list_models(self, connection: ProviderConnection) -> list[RemoteModel]:
        """Получает список моделей через GET /models."""
        url = f"{connection.base_url.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=self._headers(connection))
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "Таймаут провайдера", True) from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_UNREACHABLE", "Провайдер недоступен") from exc

        if resp.status_code != 200:
            raise normalize_http_status(resp.status_code)

        models: list[RemoteModel] = []
        for item in resp.json().get("data", []):
            external_id = item.get("id") or ""
            if not external_id:
                continue
            capabilities = [Capability.CHAT.value, Capability.STREAMING.value]
            # Поддержка управления рассуждениями — данные от провайдера, а не
            # догадка по имени модели.
            if _declares_reasoning(item):
                capabilities.append(Capability.REASONING.value)
            models.append(
                RemoteModel(
                    external_id=external_id,
                    display_name=item.get("name") or external_id,
                    capabilities=capabilities,
                    context_limit=item.get("context_length"),
                    pricing=_parse_pricing(item),
                )
            )
        return models

    async def stream_chat(
        self, connection: ProviderConnection, request: ChatRequest
    ) -> AsyncIterator[ChatChunk]:
        """Потоковый чат через POST /chat/completions (SSE).

        Возвращает части текста; usage приходит в финальном chunk у совместимых
        провайдеров. Ошибки нормализуются в ProviderError.
        """
        url = f"{connection.base_url.rstrip('/')}/chat/completions"
        messages: list[dict] = [{"role": m.role, "content": m.content} for m in request.messages]
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {"model": request.model, "messages": messages, "stream": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        self._apply_reasoning(payload, connection, request)

        timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, read=STREAM_READ_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=self._headers(connection)
                ) as resp:
                    if resp.status_code != 200:
                        raise normalize_http_status(resp.status_code)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = obj.get("choices") or [{}]
                        delta = (choices[0].get("delta") or {}) if choices else {}
                        yield ChatChunk(
                            content_delta=delta.get("content") or "",
                            usage=obj.get("usage"),
                            finish_reason=(choices[0].get("finish_reason") if choices else None),
                        )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "Таймаут провайдера", True) from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_UNREACHABLE", "Провайдер недоступен") from exc

    async def embed(
        self, connection: ProviderConnection, texts: list[str], model: str
    ) -> EmbeddingResult:
        """Получает эмбеддинги батча текстов через POST /embeddings."""
        url = f"{connection.base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url, json=payload, headers=self._headers(connection)
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "Таймаут провайдера", True) from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_UNREACHABLE", "Провайдер недоступен") from exc

        if resp.status_code != 200:
            raise normalize_http_status(resp.status_code)

        body = resp.json()
        data = body.get("data", [])
        vectors = [item["embedding"] for item in data]
        # usage эмбеддингов (prompt_tokens) нужен billing'у для actual-расчёта.
        usage = body.get("usage")
        return EmbeddingResult(vectors=vectors, model=model, usage=usage)

    async def chat_complete(
        self, connection: ProviderConnection, request: ChatRequest
    ) -> ChatCompletionResult:
        """Непотоковый чат (для RAG-синтеза): текст ответа и usage."""
        url = f"{connection.base_url.rstrip('/')}/chat/completions"
        messages: list[dict] = [{"role": m.role, "content": m.content} for m in request.messages]
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})
        payload: dict = {"model": request.model, "messages": messages, "stream": False}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        self._apply_reasoning(payload, connection, request)

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url, json=payload, headers=self._headers(connection)
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "Таймаут провайдера", True) from exc
        except httpx.RequestError as exc:
            raise ProviderError("PROVIDER_UNREACHABLE", "Провайдер недоступен") from exc

        if resp.status_code != 200:
            raise normalize_http_status(resp.status_code)

        body = resp.json()
        choices = body.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        # usage непотокового чата (prompt/completion tokens) для actual-расчёта.
        return ChatCompletionResult(text=text, usage=body.get("usage"))
