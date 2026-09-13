"""Общие зависимости FastAPI: текущий пользователь.

Извлекает Bearer-токен, декодирует JWT и загружает пользователя из БД.
Используется всеми защищёнными эндпоинтами.
"""
from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from personal_hub.db.engine import get_session
from personal_hub.models import User
from personal_hub.security.auth import decode_access_token
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Возвращает аутентифицированного пользователя или 401."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация.")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (pyjwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен.") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден.")
    return user
