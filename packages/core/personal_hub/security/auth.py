"""Пароли и JWT-токены.

Пароли хэшируются Argon2id (никогда не хранятся открыто). Токены подписываются
HS256 ключом, выведенным из мастер-ключа; содержат user_id и срок действия.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from personal_hub.config import get_settings

_hasher = PasswordHasher()

ACCESS_TOKEN_TTL_MINUTES = 60 * 12  # 12 часов


def _jwt_key() -> bytes:
    """Ключ подписи JWT, выведенный из мастер-ключа."""
    return hashlib.sha256(get_settings().app_master_key.encode()).digest()


def hash_password(password: str) -> str:
    """Хэширует пароль Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против хэша; возвращает False при несовпадении."""
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    """Создаёт подписанный JWT для пользователя."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, _jwt_key(), algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID:
    """Декодирует JWT и возвращает user_id; бросает jwt.InvalidTokenError."""
    payload = jwt.decode(token, _jwt_key(), algorithms=["HS256"])
    return uuid.UUID(payload["sub"])
