"""BlobStore: абстракция файлового хранилища.

Отделяет локальный диск от S3-совместимых хранилищ. Локальный адаптер
вычисляет sha256 и размер при записи. Ключи генерируются сервером (uuid)
и не должны содержать path traversal.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from personal_hub.config import get_settings

CHUNK_SIZE = 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class StoredBlob:
    """Метаданные сохранённого блоба."""

    key: str
    size_bytes: int
    sha256: str
    mime_type: str


class SizeLimitError(Exception):
    """Размер загружаемого файла превысил лимит."""

    def __init__(self, max_size: int) -> None:
        super().__init__(f"размер файла превышает лимит {max_size} байт")
        self.code = "SIZE_LIMIT_EXCEEDED"


class BlobStore(Protocol):
    """Контракт хранилища файлов."""

    async def put(
        self, stream: AsyncIterable[bytes], metadata: dict, max_size: int | None = None
    ) -> StoredBlob: ...

    def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
    def path_for(self, key: str) -> Path: ...


def _sanitize_key(key: str) -> str:
    """Проверяет ключ блоба (защита от path traversal)."""
    if not key or ".." in key or "/" in key or "\\" in key:
        raise ValueError("некорректный ключ блоба")
    return key


class LocalBlobStore:
    """Локальное файловое хранилище (filesystem)."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        """Абсолютный путь блоба по ключу."""
        return self._root / _sanitize_key(key)

    async def put(
        self,
        stream: AsyncIterable[bytes],
        metadata: dict,
        max_size: int | None = None,
    ) -> StoredBlob:
        """Пишет поток в файл, считая sha256 и размер.

        При превышении max_size файл удаляется и бросается SizeLimitError.
        """
        key = metadata.get("key") or uuid.uuid4().hex
        _sanitize_key(key)
        target = self._root / key

        hasher = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as fh:
                async for chunk in stream:
                    hasher.update(chunk)
                    size += len(chunk)
                    if max_size is not None and size > max_size:
                        raise SizeLimitError(max_size)
                    fh.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return StoredBlob(
            key=key,
            size_bytes=size,
            sha256=hasher.hexdigest(),
            mime_type=metadata.get("mime_type", "application/octet-stream"),
        )

    async def open(self, key: str) -> AsyncIterator[bytes]:
        """Читает блоб порциями."""
        path = self.path_for(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        with path.open("rb") as fh:
            while chunk := fh.read(CHUNK_SIZE):
                yield chunk

    async def delete(self, key: str) -> None:
        """Удаляет блоб; отсутствующий файл не считается ошибкой."""
        path = self.path_for(key)
        path.unlink(missing_ok=True)


_blob_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    """Возвращает singleton BlobStore (local по умолчанию)."""
    global _blob_store
    store = _blob_store
    if store is None:
        settings = get_settings()
        if settings.blob_store_driver == "local":
            store = LocalBlobStore(settings.blob_local_root)
        else:
            raise RuntimeError(f"неизвестный blob_store_driver: {settings.blob_store_driver}")
        _blob_store = store
    return store
