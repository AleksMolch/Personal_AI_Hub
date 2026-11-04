"""Локальная детекция сущностей в тексте (ADR-0007, срез 1).

Назначение: находить в тексте данные, которые нельзя отправлять наружу как
есть — email, телефоны, реквизиты, секреты, названия организаций из словаря.

Место в архитектуре: доменный модуль, вызывается локально до отправки запроса.
Внешние сервисы и модели не используются: только регулярные выражения и
пользовательский словарь.

Ограничения среза 1 (честно):
- нет NER-модели, поэтому персональные имена не распознаются;
- реквизиты ищутся по подписи («ИНН», «ОГРН») или по характерному формату,
  поэтому возможны пропуски при необычной записи;
- точность и полнота измеряются на синтетическом наборе, а не гарантируются.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class EntityCategory(StrEnum):
    """Категории данных, которые защищает режим."""

    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    ORG = "org"
    INN = "inn"
    OGRN = "ogrn"
    SNILS = "snils"
    BIK = "bik"
    ACCOUNT = "account"
    PASSPORT = "passport"
    SECRET = "secret"
    ADDRESS = "address"


class Action(StrEnum):
    """Что делать с найденной сущностью."""

    # Заменить псевдонимом с возможностью локального восстановления.
    REPLACE_REVERSIBLE = "replace_reversible"
    # Удалить: секреты нельзя восстановливать автоматически.
    REMOVE = "remove"
    # Обобщить: сохранить смысл, но убрать точное значение.
    GENERALIZE = "generalize"


@dataclass(frozen=True)
class Span:
    """Найденный фрагмент текста.

    Attributes:
        start: Начало фрагмента (включительно).
        end: Конец фрагмента (не включая).
        category: Категория сущности.
        text: Исходный текст фрагмента.
        action: Решение по обработке.
        priority: Приоритет при пересечении (больше — важнее).
    """

    start: int
    end: int
    category: EntityCategory
    text: str
    action: Action
    priority: int = 0


# Регулярные выражения: (категория, шаблон, действие, приоритет).
# Приоритет выше у секретов: если строка похожа и на URL, и на ключ, побеждает
# ключ, потому что его утечка необратима.
_RULES: tuple[tuple[EntityCategory, re.Pattern[str], Action, int], ...] = (
    (
        EntityCategory.SECRET,
        re.compile(
            r"(?i)\b(?:api[_-]?key|token|password|пароль|секрет)\b\s*[:=]\s*\S+"
            r"|\bsk-[A-Za-z0-9_-]{10,}\b"
            r"|\btvly-[A-Za-z0-9]{8,}\b"
            r"|\bAIza[0-9A-Za-z_-]{20,}\b"
            r"|\bBearer\s+[A-Za-z0-9._-]{16,}\b"
        ),
        Action.REMOVE,
        100,
    ),
    (
        EntityCategory.EMAIL,
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        Action.REPLACE_REVERSIBLE,
        60,
    ),
    (
        EntityCategory.SNILS,
        re.compile(r"\b\d{3}-\d{3}-\d{3}[ -]?\d{2}\b"),
        Action.REPLACE_REVERSIBLE,
        55,
    ),
    (
        EntityCategory.OGRN,
        re.compile(r"(?i)огрн(?:\s*ип)?\s*[:№]?\s*(\d{13,15})"),
        Action.REPLACE_REVERSIBLE,
        50,
    ),
    (
        EntityCategory.INN,
        re.compile(r"(?i)инн\s*[:№]?\s*(\d{10}|\d{12})"),
        Action.REPLACE_REVERSIBLE,
        50,
    ),
    (
        EntityCategory.BIK,
        re.compile(r"(?i)бик\s*[:№]?\s*(\d{9})"),
        Action.REPLACE_REVERSIBLE,
        50,
    ),
    (
        EntityCategory.ACCOUNT,
        re.compile(r"(?i)(?:расч[её]тный\s+сч[её]т|сч[её]т)\s*[:№]?\s*(\d{20})"),
        Action.REPLACE_REVERSIBLE,
        50,
    ),
    (
        EntityCategory.PASSPORT,
        re.compile(
            r"(?i)паспорт\S*\s*(?:серия\s*)?(\d{2}\s?\d{2})\s*(?:№|номер)?\s*(\d{6})"
        ),
        Action.REPLACE_REVERSIBLE,
        50,
    ),
    (
        EntityCategory.PHONE,
        re.compile(r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b"),
        Action.REPLACE_REVERSIBLE,
        45,
    ),
    (
        EntityCategory.URL,
        re.compile(r"https?://[^\s<>\"']+"),
        Action.REPLACE_REVERSIBLE,
        40,
    ),
    (
        EntityCategory.ADDRESS,
        re.compile(
            r"(?i)\b(?:г\.\s*[А-ЯЁ][а-яё-]+|ул\.\s*[А-ЯЁ][\w\s-]{2,30}"
            r"|street\s+\d+|д\.\s*\d+[А-Яа-я]?)\b"
        ),
        Action.REPLACE_REVERSIBLE,
        30,
    ),
)


def detect(
    text: str,
    *,
    dictionary: dict[str, list[str]] | None = None,
) -> list[Span]:
    """Находит защищаемые сущности в тексте.

    Пересечения разрешаются в пользу более приоритетной и более длинной
    сущности: секрет важнее URL, длинное название организации важнее короткого.

    Args:
        text: Исходный текст (сообщение, фрагмент документа).
        dictionary: Пользовательский словарь «категория → значения» (например,
            названия организаций и объектов). Сравнение без учёта регистра,
            длинные значения проверяются первыми.

    Returns:
        Отсортированный по позиции список непересекающихся фрагментов.
    """
    spans: list[Span] = []

    for category, pattern, action, priority in _RULES:
        for match in pattern.finditer(text):
            spans.append(
                Span(
                    start=match.start(),
                    end=match.end(),
                    category=category,
                    text=match.group(0),
                    action=action,
                    priority=priority,
                )
            )

    if dictionary:
        for category_name, values in dictionary.items():
            try:
                category = EntityCategory(category_name)
            except ValueError:
                # Неизвестные категории словаря игнорируются, а не ломают разбор.
                continue
            for value in sorted(values, key=len, reverse=True):
                if not value.strip():
                    continue
                for match in re.finditer(re.escape(value), text, re.IGNORECASE):
                    spans.append(
                        Span(
                            start=match.start(),
                            end=match.end(),
                            category=category,
                            text=match.group(0),
                            action=Action.REPLACE_REVERSIBLE,
                            priority=70,
                        )
                    )

    return _resolve_overlaps(spans)


def _resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Оставляет непересекающиеся фрагменты, выбирая важнейшие.

    Сортировка: сначала приоритет, затем длина (длиннее — важнее), затем начало.
    Так «ИНН 7707083893» целиком важнее случайного совпадения внутри, а секрет
    важнее URL, в котором он может встречаться.
    """
    ordered = sorted(
        spans, key=lambda span: (-span.priority, -(span.end - span.start), span.start)
    )
    chosen: list[Span] = []
    for span in ordered:
        if all(span.end <= other.start or span.start >= other.end for other in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda span: span.start)
