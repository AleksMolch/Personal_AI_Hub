"""Эндпоинты цен моделей (versioned PriceSnapshot).

POST создаёт новый снапшот; GET возвращает историю цен модели. Отдельный
эндпоинт `/prices/extract` разбирает страницу тарифов провайдера и возвращает
кандидатов на цены — БЕЗ сохранения: значения обязан подтвердить пользователь.

Разбор поддерживает три режима (ADR-0006):
- `static` — регулярные выражения по HTML: бесплатно и детерминированно;
- `rendered` — headless-браузер в отдельном контейнере, когда цены дорисовывает
  JavaScript;
- `llm` — платный вызов модели со строгим JSON-контрактом, когда вёрстка
  нестандартная. Проходит через бюджетный контур: резерв до вызова, settlement
  после, UsageRecord с операцией `price_llm_extract`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from personal_hub.config import get_settings
from personal_hub.costs import estimate_tokens
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from personal_hub.pricebot import render_page
from personal_hub.pricing_import import (
    PriceImportError,
    extract_price_candidates,
    fetch_pricing_page,
    html_to_lines,
)
from personal_hub.pricing_llm import (
    build_extraction_prompt,
    parse_extraction_result,
    system_prompt,
)
from personal_hub.providers.base import ChatMessage, ChatRequest, ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import (
    cancel_external_call,
    get_latest_price,
    reserve_external_call,
    settle_external_call,
)
from app.deps import get_current_user
from app.schemas import (
    PriceCreate,
    PriceImportCandidate,
    PriceImportRequest,
    PriceImportResult,
    PriceOut,
)

router = APIRouter(prefix="/api/v1/prices", tags=["prices"])

# Сколько токенов просить у модели на JSON-ответ: четырём полям хватает с
# запасом, а завышенный лимит увеличивал бы резерв бюджета.
_LLM_OUTPUT_TOKENS = 512

# Коды ошибок загрузки → HTTP-статусы. Всё остальное считается 400.
_FETCH_STATUS = {
    "PRICE_IMPORT_FORBIDDEN_HOST": status.HTTP_403_FORBIDDEN,
    "PRICE_IMPORT_UNREACHABLE": status.HTTP_502_BAD_GATEWAY,
    "PRICE_IMPORT_TIMEOUT": status.HTTP_502_BAD_GATEWAY,
    "PRICEBOT_UNREACHABLE": status.HTTP_502_BAD_GATEWAY,
    "PRICEBOT_TIMEOUT": status.HTTP_502_BAD_GATEWAY,
    "PRICEBOT_FAILED": status.HTTP_502_BAD_GATEWAY,
    "PRICE_IMPORT_LLM_BAD_RESPONSE": status.HTTP_502_BAD_GATEWAY,
    "PRICE_IMPORT_LLM_NO_VALUES": status.HTTP_502_BAD_GATEWAY,
}


def _raise_import_error(exc: PriceImportError) -> NoReturn:
    """Преобразует ошибку разбора в HTTPException со стабильным кодом."""
    raise HTTPException(
        _FETCH_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        f"{exc.message} ({exc.code})",
    ) from exc


async def _owned_model(
    session: AsyncSession, user: User, model_profile_id: uuid.UUID
) -> ModelProfile:
    result = await session.execute(
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(
            ModelProfile.id == model_profile_id,
            ProviderCredential.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель не найдена.")
    return model


async def _llm_target(
    session: AsyncSession, user: User, model_profile_id: uuid.UUID | None
) -> tuple[ModelProfile, ProviderCredential, PriceSnapshot]:
    """Выбирает модель для LLM-извлечения и её цену.

    Порядок: явно указанная модель → первая модель пользователя с заданной
    ценой. Без цены платный вызов запрещён (strict billing), поэтому такая
    модель не подходит: иначе расход ушёл бы мимо бюджета.

    Args:
        session: Асинхронная сессия.
        user: Текущий пользователь.
        model_profile_id: Модель, выбранная пользователем (может быть None).

    Returns:
        Кортеж (модель, провайдер, действующая цена).

    Raises:
        HTTPException: 404 для чужой модели, 400 если нет модели с ценой.
    """
    if model_profile_id is not None:
        model = await _owned_model(session, user, model_profile_id)
        price = await get_latest_price(session, model.id)
        if price is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "У выбранной модели не задана цена — платный вызов без неё "
                "невозможен. Задайте цену или выберите другую модель.",
            )
        provider = await session.get(ProviderCredential, model.provider_id)
        if provider is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Провайдер модели не найден."
            )
        return model, provider, price

    stmt = (
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .join(PriceSnapshot, PriceSnapshot.model_profile_id == ModelProfile.id)
        .where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.enabled.is_(True),
            ModelProfile.enabled.is_(True),
        )
        .order_by(PriceSnapshot.effective_at.desc())
        .limit(1)
    )
    picked = (await session.execute(stmt)).scalars().first()
    if picked is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Для извлечения через LLM нужна хотя бы одна модель с заданной "
            "ценой: платный вызов должен проходить через бюджет.",
        )
    price = await get_latest_price(session, picked.id)
    provider = await session.get(ProviderCredential, picked.provider_id)
    if price is None or provider is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Не удалось определить цену или провайдера модели для LLM-разбора.",
        )
    return picked, provider, price


def _to_candidates(
    pairs: list[tuple[str, Decimal, str, float]],
) -> list[PriceImportCandidate]:
    """Собирает DTO кандидатов из кортежей (поле, значение, фрагмент, вес)."""
    return [
        PriceImportCandidate(
            field=field,
            value=value,
            snippet=snippet,
            confidence=confidence,
        )
        for field, value, snippet, confidence in pairs
    ]


@router.get("", response_model=list[PriceOut])
async def list_prices(
    model_profile_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PriceOut]:
    """Возвращает историю цен: по модели или по всем моделям пользователя.

    Args:
        model_profile_id: Необязательный фильтр по профилю модели.
        user: Текущий пользователь.
        session: Асинхронная сессия БД.

    Returns:
        Список снимков цен, свежие первыми.

    Raises:
        HTTPException: 404, если запрошена чужая модель.
    """
    stmt = select(PriceSnapshot).order_by(PriceSnapshot.effective_at.desc())
    if model_profile_id is not None:
        await _owned_model(session, user, model_profile_id)
        stmt = stmt.where(PriceSnapshot.model_profile_id == model_profile_id)
    else:
        # Только модели пользователя.
        subq = (
            select(ModelProfile.id)
            .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
            .where(ProviderCredential.user_id == user.id)
        )
        stmt = stmt.where(PriceSnapshot.model_profile_id.in_(subq))
    result = await session.execute(stmt.limit(200))
    return [PriceOut.model_validate(p) for p in result.scalars().all()]


@router.post("/extract", response_model=PriceImportResult)
async def extract_prices(
    payload: PriceImportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceImportResult:
    """Разбирает страницу тарифов и возвращает кандидатов на цены.

    Ничего не сохраняет: у провайдеров нет машинно-читаемого контракта на
    страницу тарифов, поэтому найденные значения — только подсказка. Пользователь
    обязан сверить их со страницей и подтвердить через `POST /prices`.

    Args:
        payload: Адрес страницы и режим разбора.
        user: Текущий пользователь.
        session: Асинхронная сессия (нужна для LLM-режима и цены).

    Returns:
        Кандидаты, напоминание о проверке и метод, которым они получены.

    Raises:
        HTTPException: 400 при некритичных ошибках, 402 при превышении бюджета,
            403 при попытке загрузить внутренний адрес, 502 при недоступности
            сайта или сервиса рендера.
    """
    note = (
        "Значения найдены автоматически и могут быть неверными: страницы "
        "тарифов меняются, а единицы измерения у провайдеров различаются. "
        "Сверьте каждое значение со страницей провайдера и только потом "
        "сохраняйте цену."
    )

    if payload.method == "llm":
        return await _extract_with_llm(payload, user, session, note)

    if payload.method == "rendered":
        text = await _render_text(payload.url)
        pairs = _pairs_from_static(text)
        return PriceImportResult(
            source_url=payload.url,
            candidates=_to_candidates(pairs),
            note=(
                "Страница открыта в headless-браузере и отрендерена. "
                "Проверьте значения: разбор текста остаётся эвристическим. "
                + note
            ),
            method="rendered",
        )

    # static: загрузка HTML и разбор регулярными выражениями
    try:
        html = await fetch_pricing_page(payload.url)
    except PriceImportError as exc:
        _raise_import_error(exc)
    pairs = _pairs_from_static("\n".join(html_to_lines(html)))

    if pairs:
        return PriceImportResult(
            source_url=payload.url,
            candidates=_to_candidates(pairs),
            note=note,
            method="static",
        )

    # Статический разбор ничего не нашёл. Если рендер включён — пробуем его
    # автоматически: это главный сценарий «цены рисует JavaScript».
    settings = get_settings()
    if not settings.pricebot_enabled:
        return PriceImportResult(
            source_url=payload.url,
            candidates=[],
            note=(
                "Обычный разбор не нашёл цен. Возможно, таблица дорисовывается "
                "JavaScript — включите профиль `pricebot` на сервере, и разбор "
                "повторится в браузере. Либо попробуйте режим «через LLM»."
            ),
            method="static",
        )

    try:
        rendered_text = await _render_text(payload.url)
    except PriceImportError as exc:
        # Рендер мог не сработать (Cloudflare, тяжёлая страница). Возвращаем
        # пустой результат с объяснением, а не ошибку: пользователь увидит,
        # что делать дальше.
        return PriceImportResult(
            source_url=payload.url,
            candidates=[],
            note=(
                "Обычный разбор не нашёл цен, а рендер не удался: "
                f"{exc.message} ({exc.code}). Введите цены вручную или "
                "попробуйте режим «через LLM»."
            ),
            method="static",
        )
    return PriceImportResult(
        source_url=payload.url,
        candidates=_to_candidates(_pairs_from_static(rendered_text)),
        note=(
            "Цены найдены после рендера страницы в headless-браузере. "
            "Проверьте значения перед сохранением. " + note
        ),
        method="rendered",
    )


def _pairs_from_static(text: str) -> list[tuple[str, Decimal, str, float]]:
    """Прогоняет статический разбор по тексту и приводит к кортежам."""
    return [
        (candidate.field, candidate.value, candidate.snippet, candidate.confidence)
        for candidate in extract_price_candidates(text)
    ]


async def _render_text(url: str) -> str:
    """Рендерит страницу через сервис `pricebot` с учётом настроек.

    Args:
        url: Публичный адрес страницы.

    Returns:
        Текст отрендеренной страницы.

    Raises:
        HTTPException: 400, если рендер выключен на сервере.
        PriceImportError: При сбое сервиса рендера.
    """
    settings = get_settings()
    if not settings.pricebot_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Рендер страницы выключен на сервере (PRICEBOT_ENABLED=0).",
        )
    return await render_page(
        url,
        service_url=settings.pricebot_url,
        timeout_seconds=settings.pricebot_timeout_seconds,
    )


async def _extract_with_llm(
    payload: PriceImportRequest,
    user: User,
    session: AsyncSession,
    note: str,
) -> PriceImportResult:
    """Извлекает цены моделью: платный вызов через бюджетный контур.

    Порядок важен для денег: цена модели обязательна, резерв создаётся ДО
    вызова, а при ошибке резерв освобождается. Если провайдер вернул usage,
    запись пишется как actual, иначе остаётся оценкой.
    """
    try:
        html = await fetch_pricing_page(payload.url)
    except PriceImportError as exc:
        _raise_import_error(exc)

    text = "\n".join(html_to_lines(html))
    if not text.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Страница не содержит текста для анализа (возможно, нужен рендер). "
            "(PRICE_IMPORT_LLM_EMPTY_PAGE)",
        )

    model, provider, price = await _llm_target(session, user, payload.model_profile_id)
    prompt = build_extraction_prompt(text)
    units = {
        "operation": "price_llm_extract",
        "input_tokens": estimate_tokens(prompt),
        "output_tokens": _LLM_OUTPUT_TOKENS,
    }

    # Резервируем ДО обращения к провайдеру: иначе платный вызов мог бы уйти
    # мимо лимита. BudgetExceededError обрабатывается глобально (402).
    billing = await reserve_external_call(session, user.id, price=price, units=units)

    connection = ProviderConnection(
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=get_cipher().decrypt(provider.encrypted_secret),
    )
    adapter = get_adapter(provider.provider_type)
    try:
        completion = await adapter.chat_complete(
            connection,
            ChatRequest(
                model=model.external_model_id,
                messages=[ChatMessage(role="user", content=prompt)],
                system=system_prompt(),
                max_tokens=_LLM_OUTPUT_TOKENS,
            ),
        )
    except Exception:
        # Вызов не состоялся — резерв возвращаем, иначе бюджет «залипнет».
        await cancel_external_call(session, billing=billing)
        raise

    # Вызов уже оплачен провайдером, поэтому расход фиксируем ДО разбора
    # ответа: даже если модель вернула мусор, деньги потрачены.
    await settle_external_call(
        session,
        user_id=user.id,
        provider_id=provider.id,
        model_profile_id=model.id,
        billing=billing,
        usage=completion.usage,
    )

    try:
        values = parse_extraction_result(completion.text)
    except PriceImportError as exc:
        # Расход уже зафиксирован (вызов оплачен), поэтому отвечаем
        # стабильным кодом, а не 500: пользователь должен понять, что делать.
        _raise_import_error(exc)

    pairs: list[tuple[str, Decimal, str, float]] = [
        (
            field,
            value,
            f"Извлечено моделью {model.display_name} из текста страницы",
            0.5,
        )
        for field, value in values.items()
        if value is not None
    ]
    if not pairs:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Модель не вернула ни одного значения. (PRICE_IMPORT_LLM_NO_VALUES)",
        )

    return PriceImportResult(
        source_url=payload.url,
        candidates=_to_candidates(pairs),
        note=(
            "Значения извлечены моделью, а не разметкой страницы: возможны "
            "ошибки в числах. Проверьте их по странице провайдера. Вызов "
            "оплачен и учтён в расходах. " + note
        ),
        method="llm",
        llm_model=model.display_name or model.external_model_id,
    )


@router.post("", response_model=PriceOut, status_code=status.HTTP_201_CREATED)
async def create_price(
    payload: PriceCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceOut:
    """Создаёт новую версию цены модели (не изменяет исторические записи)."""
    await _owned_model(session, user, payload.model_profile_id)
    snapshot = PriceSnapshot(
        model_profile_id=payload.model_profile_id,
        currency=payload.currency.upper(),
        input_per_million=payload.input_per_million,
        output_per_million=payload.output_per_million,
        cache_read_per_million=payload.cache_read_per_million,
        cache_write_per_million=payload.cache_write_per_million,
        source=payload.source,
        source_url=payload.source_url,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return PriceOut.model_validate(snapshot)
