"""Vault псевдонимов: обратимая замена сущностей (ADR-0007).

Назначение: хранить соответствие «псевдоним → исходное значение» локально и
шифрованно. Псевдонимы стабильны в пределах подготовки: `[EMAIL_1]`,
`[ORG_2]`, `[INN_1]`.

Место в архитектуре: доменный модуль. В срезе 1 реализовано in-memory
хранилище с шифрованием значений мастер-ключом; постоянное хранение в
PostgreSQL добавляется следующей миграцией (см. ADR-0007, срез 2).

Ключевые инварианты:
1. Исходные значения не покидают процесс в открытом виде: в хранилище лежит
   шифротекст, наружу (в API) vault не отдаётся.
2. Одинаковое значение в одной области получает один и тот же псевдоним —
   иначе модель увидит разные токены для одной организации и запутается.
3. Псевдоним нельзя «угадать» и подделать: восстановление возможно только по
   записи в vault, а не по шаблону строки.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VaultEntry:
    """Запись vault: псевдоним и зашифрованное значение.

    Attributes:
        placeholder: Псевдоним вида `[EMAIL_1]`.
        category: Категория сущности (email, org, inn, secret и т. д.).
        ciphertext: Зашифрованное исходное значение.
        scope: Область стабильности (id подготовки).
    """

    placeholder: str
    category: str
    ciphertext: str
    scope: str = ""


@dataclass
class EntityVault:
    """Vault псевдонимов в памяти с шифрованием значений.

    Args:
        encrypt: Функция шифрования строки (по умолчанию — Fernet-контур
            приложения).
        decrypt: Функция расшифрования.

    Attributes:
        entries: Записи по псевдониму.
        _by_value: Обратный индекс «область + категория + значение → псевдоним»
            для стабильности токенов.
    """

    encrypt: Callable[[str], str]
    decrypt: Callable[[str], str]
    entries: dict[str, VaultEntry] = field(default_factory=dict)
    _by_value: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def add(self, scope: str, category: str, value: str) -> str:
        """Возвращает псевдоним для значения, создавая его при необходимости.

        Args:
            scope: Область стабильности (например, id подготовки).
            category: Категория сущности.
            value: Исходное значение.

        Returns:
            Псевдоним вида `[CATEGORY_N]`; для одного значения в одной области
            всегда один и тот же.
        """
        key = (scope, category, value)
        existing = self._by_value.get(key)
        if existing is not None:
            return existing

        # Нумерация в пределах области и категории, чтобы человеку было проще
        # читать sanitized-текст: [ORG_1], [ORG_2] — разные организации.
        # Считаем только записи той же области, иначе вторая подготовка
        # получила бы [ORG_2] без единой организации в тексте.
        index = 1 + sum(
            1
            for entry in self.entries.values()
            if entry.scope == scope
            and entry.placeholder.startswith(f"[{category.upper()}_")
        )
        placeholder = f"[{category.upper()}_{index}]"
        self.entries[placeholder] = VaultEntry(
            placeholder=placeholder,
            category=category,
            ciphertext=self.encrypt(value),
            scope=scope,
        )
        self._by_value[key] = placeholder
        return placeholder

    def value(self, placeholder: str) -> str | None:
        """Расшифровывает значение по псевдониму."""
        entry = self.entries.get(placeholder)
        return self.decrypt(entry.ciphertext) if entry else None

    def category(self, placeholder: str) -> str | None:
        """Возвращает категорию псевдонима."""
        entry = self.entries.get(placeholder)
        return entry.category if entry else None

    def values(self) -> dict[str, str]:
        """Возвращает карту «псевдоним → исходное значение» для восстановления."""
        return {
            placeholder: self.decrypt(entry.ciphertext)
            for placeholder, entry in self.entries.items()
        }
