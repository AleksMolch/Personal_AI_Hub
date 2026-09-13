"""Auth endpoints: bootstrap первого администратора, вход и текущий пользователь.

Local-first: первый вызов /bootstrap создаёт администратора только если
пользователей ещё нет. При localhost-bind это безопасно; для LAN обязательна
HTTPS + осознанное включение.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.db.engine import get_session
from personal_hub.models import User
from personal_hub.security.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import BootstrapRequest, LoginRequest, TokenResponse, UserOut

logger = logging.getLogger("api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return int(result.scalar_one())


def _token_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap(
    payload: BootstrapRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Создаёт первого администратора (работает только при пустой БД)."""
    if await _count_users(session) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Администратор уже создан.")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("bootstrap_admin", extra={"extra_fields": {"username": user.username}})
    return _token_for(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Аутентифицирует пользователя и выдаёт токен."""
    result = await session.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    # Единое сообщение для неверного логина/пароля, чтобы не раскрывать факт
    # существования пользователя.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль.")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена.")
    return _token_for(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    """Возвращает текущего аутентифицированного пользователя."""
    return user
