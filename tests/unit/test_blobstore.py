"""Тесты LocalBlobStore: запись, чтение, удаление и лимит размера."""
from __future__ import annotations

import hashlib

import pytest

from personal_hub.blobstore import LocalBlobStore, SizeLimitError


async def _chunks(data: bytes):
    yield data


@pytest.mark.asyncio
async def test_put_open_delete(tmp_path) -> None:
    store = LocalBlobStore(str(tmp_path))
    blob = await store.put(_chunks(b"hello world"), {"mime_type": "text/plain"})

    assert blob.size_bytes == 11
    assert blob.sha256 == hashlib.sha256(b"hello world").hexdigest()
    assert blob.mime_type == "text/plain"

    content = b"".join([c async for c in store.open(blob.key)])
    assert content == b"hello world"

    await store.delete(blob.key)
    assert not store.path_for(blob.key).exists()


@pytest.mark.asyncio
async def test_put_size_limit(tmp_path) -> None:
    store = LocalBlobStore(str(tmp_path))
    with pytest.raises(SizeLimitError):
        await store.put(_chunks(b"x" * 100), {}, max_size=10)


@pytest.mark.asyncio
async def test_open_missing_key_raises(tmp_path) -> None:
    store = LocalBlobStore(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        async for _ in store.open("missing"):
            pass
