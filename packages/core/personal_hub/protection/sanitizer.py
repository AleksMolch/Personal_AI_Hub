"""Санитизация текста и обратное восстановление ответа (ADR-0007).

Назначение: заменить найденные сущности псевдонимами (или удалить секреты),
получить безопасный для внешней модели текст и затем локально восстановить
исходные значения в ответе.

Место в архитектуре: доменный модуль между детектором и провайдером. В гибриде
наружу уходит только результат `sanitize`; `restore` вызывается локально при
показе ответа.

Инварианты:
1. Восстановление — только точное совпадение псевдонима из vault. Поиск по
   подстрокам запрещён, иначе восстановились бы случайные совпадения.
2. Нет рекурсии: подставленный текст повторно не сканируется.
3. Внутри URL, markdown-ссылок и HTML-тегов не восстанавливаем: иначе значение
   попало бы в кликабельную ссылку или картинку и утекло через запрос браузера.
4. Секреты не восстанавливаются автоматически: только явное действие
   пользователя.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from personal_hub.protection.detector import Action, EntityCategory, Span
from personal_hub.protection.vault import EntityVault

# Маркер удалённого секрета: текст остаётся читаемым, значения нет.
REMOVED_MARKER = "[удалено]"

# Псевдоним: [CATEGORY_N]. Категории — только заглавные латинские буквы и цифры.
_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")

# Зоны, внутри которых восстановление запрещено.
_PROTECTED_ZONES = (
    re.compile(r"https?://[^\s<>\"']+"),
    re.compile(r"\]\([^)]*\)"),  # адрес markdown-ссылки
    re.compile(r"<[^>]+>"),  # HTML-тег
)


@dataclass(frozen=True)
class SanitizedEntity:
    """Одна заменённая сущность.

    Attributes:
        placeholder: Псевдоним либо маркер удаления.
        category: Категория.
        original_length: Длина исходного значения (для статистики, без текста).
    """

    placeholder: str
    category: str
    original_length: int


@dataclass
class SanitizedText:
    """Результат санитизации.

    Attributes:
        text: Текст, безопасный для отправки внешней модели.
        entities: Список замен с категориями.
        removed: Сколько фрагментов удалено без восстановления.
    """

    text: str
    entities: list[SanitizedEntity] = field(default_factory=list)
    removed: int = 0


@dataclass
class RestorationResult:
    """Результат локального восстановления ответа.

    Attributes:
        text: Восстановленный текст.
        restored: Сколько псевдонимов заменено.
        skipped: Псевдонимы, которые не восстановлены, с причиной.
    """

    text: str
    restored: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


def sanitize(text: str, spans: list[Span], vault: EntityVault, scope: str) -> SanitizedText:
    """Заменяет найденные сущности псевдонимами или удаляет их.

    Замены выполняются от конца к началу, чтобы позиции не сдвигались.

    Args:
        text: Исходный текст.
        spans: Результат `detect` (непересекающиеся фрагменты).
        vault: Vault для стабильных псевдонимов.
        scope: Область стабильности (id подготовки).

    Returns:
        Безопасный текст и список замен.
    """
    entities: list[SanitizedEntity] = []
    removed = 0
    result = text

    for span in sorted(spans, key=lambda item: item.start, reverse=True):
        if span.action == Action.REMOVE:
            replacement = REMOVED_MARKER
            removed += 1
            entities.append(
                SanitizedEntity(
                    placeholder=REMOVED_MARKER,
                    category=span.category.value,
                    original_length=len(span.text),
                )
            )
        else:
            placeholder = vault.add(scope, span.category.value, span.text)
            replacement = placeholder
            entities.append(
                SanitizedEntity(
                    placeholder=placeholder,
                    category=span.category.value,
                    original_length=len(span.text),
                )
            )
        result = result[: span.start] + replacement + result[span.end :]

    entities.reverse()
    return SanitizedText(text=result, entities=entities, removed=removed)


def restore(
    text: str,
    vault: EntityVault,
    *,
    allow_secret_placeholders: set[str] | None = None,
) -> RestorationResult:
    """Восстанавливает исходные значения по псевдонимам локально.

    Args:
        text: Ответ модели с псевдонимами.
        vault: Vault с картой соответствий.
        allow_secret_placeholders: Псевдонимы секретов, которые пользователь
            явно разрешил показать. По умолчанию секреты не восстанавливаются.

    Returns:
        Восстановленный текст, счётчик замен и список пропущенных псевдонимов
        с причиной.
    """
    allowed_secrets = allow_secret_placeholders or set()
    zones = [
        (match.start(), match.end())
        for pattern in _PROTECTED_ZONES
        for match in pattern.finditer(text)
    ]

    result: list[str] = []
    position = 0
    restored = 0
    skipped: list[tuple[str, str]] = []

    for match in _PLACEHOLDER_RE.finditer(text):
        placeholder = match.group(0)
        start, end = match.span()

        if _inside_zone(start, zones):
            skipped.append((placeholder, "внутри ссылки или тега"))
            continue

        category = vault.category(placeholder)
        value = vault.value(placeholder)
        if value is None or category is None:
            skipped.append((placeholder, "псевдоним неизвестен"))
            continue
        if category == EntityCategory.SECRET.value and placeholder not in allowed_secrets:
            skipped.append((placeholder, "секрет скрыт"))
            continue

        result.append(text[position:start])
        result.append(value)
        position = end
        restored += 1

    result.append(text[position:])
    return RestorationResult(
        text="".join(result), restored=restored, skipped=skipped
    )


def _inside_zone(start: int, zones: list[tuple[int, int]]) -> bool:
    """True, если позиция попадает внутрь защищённой зоны."""
    return any(zone_start <= start < zone_end for zone_start, zone_end in zones)
