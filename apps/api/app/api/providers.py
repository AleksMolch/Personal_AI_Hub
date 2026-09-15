"""CRUD провайдеров, проверка соединения и синхронизация моделей.

Ключ принимается только на вход; на выход отдаётся маска. Проверка соединения
не сохраняет ничего и не совершает платных вызовов (только GET /models).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.db.engine import get_session
from personal_hub.models import ModelProfile, PriceSnapshot, ProviderCredential, User
from personal_hub.providers.base import ProviderConnection, RemotePricing
from personal_hub.providers.presets import PRESETS
from personal_hub.providers.registry import SUPPORTED_PROVIDER_TYPES, get_adapter
from personal_hub.security.crypto import get_cipher, mask_secret
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import get_latest_price
from app.deps import get_current_user
from app.schemas import (
    ModelProfileOut,
    ProviderCreate,
    ProviderOut,
    ProviderPresetOut,
    ProviderTestResult,
    ProviderUpdate,
)

logger = logging.getLogger("api.providers")

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def _to_out(provider: ProviderCredential) -> ProviderOut:
    """Собирает DTO с маской ключа (ключ расшифровывается только для маски)."""
    try:
        mask = mask_secret(get_cipher().decrypt(provider.encrypted_secret))
    except ValueError:
        mask = "••••"
    return ProviderOut(
        id=provider.id,
        provider_type=provider.provider_type,
        display_name=provider.display_name,
        base_url=provider.base_url,
        enabled=provider.enabled,
        priority=provider.priority,
        currency=provider.currency,
        key_mask=mask,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


async def _get_owned_provider(
    provider_id, user: User, session: AsyncSession
) -> ProviderCredential:
    """Возвращает провайдера, принадлежащего пользователю, или 404."""
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.id == provider_id,
            ProviderCredential.user_id == user.id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Провайдер не найден.")
    return provider


def _connection_for(provider: ProviderCredential) -> ProviderConnection:
    """Строит соединение, расшифровывая ключ провайдера."""
    return ProviderConnection(
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=get_cipher().decrypt(provider.encrypted_secret),
    )


async def _import_price(
    session: AsyncSession,
    provider: ProviderCredential,
    model: ModelProfile,
    pricing: RemotePricing,
) -> None:
    """Создаёт PriceSnapshot из цены провайдера, если цена изменилась.

    Ручная цена (source="manual") имеет приоритет и не перезаписывается.
    Повторная синхронизация без изменения цены не плодит версии.
    """
    latest = await get_latest_price(session, model.id)
    if latest is not None and latest.source == "manual":
        return
    if (
        latest is not None
        and latest.currency == provider.currency.upper()
        and latest.input_per_million == pricing.input_per_million
        and latest.output_per_million == pricing.output_per_million
        and latest.cache_read_per_million == pricing.cache_read_per_million
        and latest.cache_write_per_million == pricing.cache_write_per_million
    ):
        return
    session.add(
        PriceSnapshot(
            model_profile_id=model.id,
            currency=provider.currency.upper(),
            input_per_million=pricing.input_per_million,
            output_per_million=pricing.output_per_million,
            cache_read_per_million=pricing.cache_read_per_million,
            cache_write_per_million=pricing.cache_write_per_million,
            source="api",
            source_url=provider.base_url,
        )
    )


@router.get("/presets", response_model=list[ProviderPresetOut])
async def list_presets(
    _: User = Depends(get_current_user),
) -> list[ProviderPresetOut]:
    """Возвращает предустановки провайдеров (без секретов)."""
    return [
        ProviderPresetOut(
            provider_type=p.provider_type,
            label=p.label,
            base_url=p.base_url,
            currency=p.currency,
        )
        for p in PRESETS.values()
    ]


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[ProviderOut]:
    """Возвращает провайдеров пользователя (ключи — только маска)."""
    result = await session.execute(
        select(ProviderCredential)
        .where(ProviderCredential.user_id == user.id)
        .order_by(ProviderCredential.priority)
    )
    return [_to_out(p) for p in result.scalars().all()]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProviderOut:
    """Создаёт провайдера, шифруя API-ключ."""
    if payload.provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Неподдерживаемый тип провайдера."
        )
    provider = ProviderCredential(
        user_id=user.id,
        provider_type=payload.provider_type,
        display_name=payload.display_name,
        base_url=payload.base_url,
        encrypted_secret=get_cipher().encrypt(payload.api_key),
        currency=payload.currency.upper(),
        priority=payload.priority,
        enabled=payload.enabled,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    logger.info(
        "provider_created",
        extra={"extra_fields": {"provider_id": str(provider.id), "type": provider.provider_type}},
    )
    return _to_out(provider)


@router.get("/{provider_id}", response_model=ProviderOut)
async def get_provider(
    provider_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProviderOut:
    provider = await _get_owned_provider(provider_id, user, session)
    return _to_out(provider)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id,
    payload: ProviderUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProviderOut:
    provider = await _get_owned_provider(provider_id, user, session)
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        provider.encrypted_secret = get_cipher().encrypt(data.pop("api_key"))
    if "currency" in data and data["currency"] is not None:
        data["currency"] = data["currency"].upper()
    for field, value in data.items():
        setattr(provider, field, value)
    await session.commit()
    await session.refresh(provider)
    return _to_out(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    provider = await _get_owned_provider(provider_id, user, session)
    await session.delete(provider)
    await session.commit()


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(
    provider_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProviderTestResult:
    """Проверяет соединение; ничего не сохраняет и не совершает платных вызовов."""
    provider = await _get_owned_provider(provider_id, user, session)
    adapter = get_adapter(provider.provider_type)
    health = await adapter.health(_connection_for(provider))
    return ProviderTestResult(
        ok=health.ok,
        message=health.message,
        latency_ms=health.latency_ms,
        model_count=health.model_count,
    )


@router.post("/{provider_id}/sync-models", response_model=list[ModelProfileOut])
async def sync_models(
    provider_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ModelProfileOut]:
    """Получает модели провайдера и обновляет локальный каталог (upsert)."""
    provider = await _get_owned_provider(provider_id, user, session)
    adapter = get_adapter(provider.provider_type)
    remote_models = await adapter.list_models(_connection_for(provider))

    result = await session.execute(
        select(ModelProfile).where(ModelProfile.provider_id == provider.id)
    )
    existing = {m.external_model_id: m for m in result.scalars().all()}

    for remote in remote_models:
        model = existing.get(remote.external_id)
        if model is None:
            model = ModelProfile(
                provider_id=provider.id,
                external_model_id=remote.external_id,
                display_name=remote.display_name,
                capabilities=remote.capabilities,
                context_limit=remote.context_limit,
            )
            session.add(model)
            existing[remote.external_id] = model
        else:
            model.display_name = remote.display_name
            model.capabilities = remote.capabilities
            model.context_limit = remote.context_limit

    # Моделям нужен id до создания привязанного PriceSnapshot.
    await session.flush()

    for remote in remote_models:
        if remote.pricing is not None:
            await _import_price(session, provider, existing[remote.external_id], remote.pricing)

    await session.commit()
    for model in existing.values():
        await session.refresh(model)
    return [ModelProfileOut.model_validate(m) for m in existing.values()]
