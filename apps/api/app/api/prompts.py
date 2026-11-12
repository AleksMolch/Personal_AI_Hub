"""Библиотека промптов: CRUD персональных шаблонов пользователя.

Шаблон — это текст, который вставляется в поле ввода чата. Маршруты закрыты
авторизацией и возвращают только шаблоны текущего пользователя.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.db.engine import get_session
from personal_hub.models import PromptTemplate, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import (
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


async def _owned_template(
    session: AsyncSession, user: User, template_id: uuid.UUID
) -> PromptTemplate:
    """Возвращает шаблон пользователя или 404 для чужого/несуществующего."""
    template = await session.get(PromptTemplate, template_id)
    if template is None or template.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден.")
    return template


@router.get("", response_model=list[PromptTemplateOut])
async def list_templates(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PromptTemplateOut]:
    """Список шаблонов текущего пользователя (новые сверху)."""
    result = await session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.user_id == user.id)
        .order_by(PromptTemplate.updated_at.desc())
    )
    return [PromptTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: PromptTemplateCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptTemplateOut:
    """Создаёт шаблон промпта."""
    template = PromptTemplate(
        user_id=user.id, title=payload.title.strip(), content=payload.content
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return PromptTemplateOut.model_validate(template)


@router.patch("/{template_id}", response_model=PromptTemplateOut)
async def update_template(
    template_id: uuid.UUID,
    payload: PromptTemplateUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PromptTemplateOut:
    """Изменяет название и/или текст шаблона."""
    template = await _owned_template(session, user, template_id)
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        template.title = data["title"].strip()
    if "content" in data and data["content"] is not None:
        template.content = data["content"]
    await session.commit()
    await session.refresh(template)
    return PromptTemplateOut.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Удаляет шаблон."""
    template = await _owned_template(session, user, template_id)
    await session.delete(template)
    await session.commit()
