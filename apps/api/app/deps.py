"""Общие зависимости FastAPI: текущий пользователь.

Извлекает токен (Bearer-заголовок или query-параметр для SSE), декодирует JWT
и загружает пользователя из БД. Используется всеми защищёнными эндпоинтами.
"""
from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from personal_hub.db.engine import get_session
from personal_hub.models import User
from personal_hub.security.auth import decode_access_token
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)


async def _user_from_token(raw: str, session: AsyncSession) -> User:
    """Декодирует токен и возвращает активного пользователя или 401."""
    try:
        user_id = decode_access_token(raw)
    except (pyjwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен.") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден.")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Возвращает аутентифицированного пользователя (Bearer-заголовок)."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация.")
    return await _user_from_token(credentials.credentials, session)


async def get_current_user_sse(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Возвращает пользователя по Bearer ИЛИ query-параметру token.

    Query-параметр нужен для EventSource (SSE), который не умеет задавать
    заголовки. Для локального (localhost) режима это приемлемо.
    """
    raw = credentials.credentials if credentials is not None else token
    if raw is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация.")
    return await _user_from_token(raw, session)
