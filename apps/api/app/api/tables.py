"""Эндпоинты анализа таблиц (CSV/XLSX) через DuckDB sandbox.

Preview отдаёт только схему и первые строки. Query выполняется в read-only
режиме с запретом файловых/сетевых функций. Экспорт возвращает CSV/XLSX.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from personal_hub.blobstore import get_blob_store
from personal_hub.db.engine import get_session
from personal_hub.models import Asset, User
from personal_hub.tables import (
    TableQueryError,
    UnsupportedTableFormatError,
    export_csv,
    export_xlsx,
    load_table,
    run_query,
    schema_preview,
    xlsx_sheet_names,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import (
    TableExportRequest,
    TablePreview,
    TableQueryRequest,
    TableQueryResult,
)

router = APIRouter(prefix="/api/v1/assets", tags=["tables"])


def _detect_format(asset: Asset) -> str:
    name = asset.original_name.lower()
    if name.endswith(".csv") or asset.mime_type == "text/csv":
        return "csv"
    if name.endswith((".xlsx", ".xls")):
        return "xlsx"
    raise UnsupportedTableFormatError(name.rsplit(".", 1)[-1])


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


def _path(asset: Asset) -> str:
    return str(get_blob_store().path_for(asset.blob_key))


@router.get("/{asset_id}/table", response_model=TablePreview)
async def table_preview(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TablePreview:
    asset = await _owned_asset(session, asset_id, user)
    fmt = _detect_format(asset)
    sheets: list[str] = []
    sheet = None
    if fmt == "xlsx":
        sheets = xlsx_sheet_names(_path(asset))
        sheet = sheets[0] if sheets else None
    conn = load_table(_path(asset), fmt, sheet)
    preview = schema_preview(conn)
    return TablePreview(format=fmt, sheets=sheets, **preview)


@router.post("/{asset_id}/table/query", response_model=TableQueryResult)
async def table_query(
    asset_id: uuid.UUID,
    payload: TableQueryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TableQueryResult:
    asset = await _owned_asset(session, asset_id, user)
    fmt = _detect_format(asset)
    conn = load_table(_path(asset), fmt, payload.sheet)
    try:
        result = run_query(conn, payload.sql)
    except TableQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return TableQueryResult(**result)


@router.post("/{asset_id}/table/export")
async def table_export(
    asset_id: uuid.UUID,
    payload: TableExportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    asset = await _owned_asset(session, asset_id, user)
    fmt = _detect_format(asset)
    conn = load_table(_path(asset), fmt, payload.sheet)
    content: str | bytes
    try:
        if payload.format == "xlsx":
            content = export_xlsx(conn, payload.sql)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            suffix = "xlsx"
        else:
            content = export_csv(conn, payload.sql)
            media_type = "text/csv"
            suffix = "csv"
    except TableQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="table-export.{suffix}"'
        },
    )
