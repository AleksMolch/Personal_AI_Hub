"""Эндпоинты файлов-ассетов: загрузка, скачивание, удаление.

Загрузка потоковая с лимитом размера. Скачивание идёт через авторизованный
API (не прямая ссылка на blob). Удаление оформляется задачей (document_delete),
что делает его безопасным и идемпотентным.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from personal_hub.blobstore import SizeLimitError, get_blob_store
from personal_hub.db.engine import get_session
from personal_hub.jobs import JobType
from personal_hub.models import Asset, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.job_service import create_job
from app.schemas import AssetOut, DeleteAssetResponse

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB


async def _owned_asset(
    session: AsyncSession, asset_id: uuid.UUID, user: User
) -> Asset:
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден.")
    return asset


async def _iter_file(file: UploadFile):
    """Итератор кусков загружаемого файла (потоковая передача)."""
    while chunk := await file.read(1024 * 1024):
        yield chunk


@router.post("/uploads", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form(default="document"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetOut:
    """Загружает файл в BlobStore (потоково, с лимитом размера)."""
    store = get_blob_store()
    try:
        blob = await store.put(
            _iter_file(file),
            {
                "original_name": file.filename or "unnamed",
                "mime_type": file.content_type or "application/octet-stream",
            },
            max_size=MAX_UPLOAD_BYTES,
        )
    except SizeLimitError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    asset = Asset(
        user_id=user.id,
        kind=kind,
        status="ready",
        blob_key=blob.key,
        original_name=file.filename or "unnamed",
        mime_type=blob.mime_type,
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return AssetOut.model_validate(asset)


@router.get("", response_model=list[AssetOut])
async def list_assets(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AssetOut]:
    result = await session.execute(
        select(Asset)
        .where(Asset.user_id == user.id)
        .order_by(Asset.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [AssetOut.model_validate(a) for a in result.scalars().all()]


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetOut:
    return AssetOut.model_validate(await _owned_asset(session, asset_id, user))


@router.get("/{asset_id}/content")
async def download_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Скачивает содержимое файла через авторизованный API."""
    asset = await _owned_asset(session, asset_id, user)
    store = get_blob_store()

    async def stream():
        async for chunk in store.open(asset.blob_key):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type=asset.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{asset.original_name}"'
        },
    )


@router.delete(
    "/{asset_id}", response_model=DeleteAssetResponse, status_code=status.HTTP_202_ACCEPTED
)
async def delete_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeleteAssetResponse:
    """Создаёт задачу удаления файла (идемпотентно)."""
    asset = await _owned_asset(session, asset_id, user)
    job = await create_job(
        session,
        user_id=user.id,
        job_type=JobType.DOCUMENT_DELETE.value,
        input_json={"asset_id": str(asset.id)},
        idempotency_key=f"delete-asset-{asset.id}",
    )
    return DeleteAssetResponse(job_id=job.id)
