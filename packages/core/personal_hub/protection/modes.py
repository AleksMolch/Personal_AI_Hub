"""Режимы обработки данных (ADR-0007).

Назначение: три режима, из которых пользователь выбирает сам — без ролей,
корпоративных ограничений и списков «одобренных» провайдеров.

Место в архитектуре: доменный модуль, используется API, worker и UI. Значение
режима хранится в диалоге и попадает в снимок сообщения.
"""
from __future__ import annotations

from enum import StrEnum


class ProtectionMode(StrEnum):
    """Политика обработки запроса."""

    # Отправка разрешена; локально показываются найденные категории данных.
    CLOUD_CONTROLLED = "cloud_controlled"
    # Полный доступ к API без локальных проверок: для задач без чувствительных
    # данных. Ничего не сканируется и не псевдонимизируется.
    DIRECT_CLOUD = "direct_cloud"
    # Наружу уходит только sanitized-контекст; ответ восстанавливается локально.
    PROTECTED_HYBRID = "protected_hybrid"
    # Внешние вызовы запрещены: только локальный runtime.
    LOCAL_ONLY = "local_only"


DEFAULT_MODE = ProtectionMode.CLOUD_CONTROLLED


def is_protected(mode: str | ProtectionMode) -> bool:
    """True, если режим требует локальной подготовки и восстановления."""
    return ProtectionMode(mode) == ProtectionMode.PROTECTED_HYBRID


def allows_external_calls(mode: str | ProtectionMode) -> bool:
    """True, если режим разрешает обращения к внешним сервисам.

    Для `local_only` это False: провайдеры, веб-поиск и импорт тарифов
    запрещены, и проверка выполняется до любого сетевого вызова.
    """
    return ProtectionMode(mode) != ProtectionMode.LOCAL_ONLY
