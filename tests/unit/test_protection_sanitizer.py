"""Тесты vault, санитизации и восстановления (ADR-0007, срез 1).

Ключевые инварианты: псевдонимы стабильны, значения шифруются, секреты не
восстанавливаются автоматически, восстановление не идёт внутрь ссылок и не
повторяется рекурсивно.
"""
from __future__ import annotations

import base64

from personal_hub.protection.detector import detect
from personal_hub.protection.sanitizer import REMOVED_MARKER, restore, sanitize
from personal_hub.protection.vault import EntityVault


class _FakeCipher:
    """Обратимое «шифрование» для тестов: base64 с префиксом."""

    def encrypt(self, value: str) -> str:
        return "enc:" + base64.b64encode(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return base64.b64decode(value.removeprefix("enc:")).decode()


def _vault() -> EntityVault:
    cipher = _FakeCipher()
    return EntityVault(encrypt=cipher.encrypt, decrypt=cipher.decrypt)


def test_placeholder_is_stable_within_scope() -> None:
    """Одно значение в одной области получает один псевдоним."""
    vault = _vault()

    first = vault.add("prep-1", "org", "ООО «Ромашка»")
    second = vault.add("prep-1", "org", "ООО «Ромашка»")

    assert first == second == "[ORG_1]"


def test_different_scopes_get_different_placeholders() -> None:
    """В разных областях нумерация независима."""
    vault = _vault()

    assert vault.add("prep-1", "org", "Ромашка") == "[ORG_1]"
    assert vault.add("prep-2", "org", "Ромашка") == "[ORG_1]"


def test_ciphertext_is_not_plaintext() -> None:
    """Значение в vault хранится только в зашифрованном виде."""
    vault = _vault()
    vault.add("prep", "email", "a@b.ru")

    entry = vault.entries["[EMAIL_1]"]
    assert "a@b.ru" not in entry.ciphertext
    assert vault.value("[EMAIL_1]") == "a@b.ru"


def test_sanitize_replaces_and_removes() -> None:
    """Email заменяется псевдонимом, секрет удаляется маркером."""
    vault = _vault()
    text = "Почта: a@b.ru, ключ sk-abcdef1234567890"

    result = sanitize(text, detect(text), vault, "prep")

    assert "a@b.ru" not in result.text
    assert "[EMAIL_1]" in result.text
    assert "sk-abcdef1234567890" not in result.text
    assert REMOVED_MARKER in result.text
    assert result.removed == 1


def test_sanitize_is_idempotent() -> None:
    """Повторная санитизация уже очищенного текста ничего не меняет."""
    vault = _vault()
    text = "Почта: a@b.ru"
    once = sanitize(text, detect(text), vault, "prep")

    twice = sanitize(once.text, detect(once.text), vault, "prep")

    assert twice.text == once.text


def test_restore_returns_original_values() -> None:
    """Ответ с псевдонимами восстанавливается локально."""
    vault = _vault()
    original = "Почта: a@b.ru"
    sanitized = sanitize(original, detect(original), vault, "prep")

    restored = restore(sanitized.text, vault)

    assert restored.text == original
    assert restored.restored == 1


def test_restore_skips_unknown_placeholders() -> None:
    """Незнакомый псевдоним остаётся как есть, а не подменяется догадкой."""
    vault = _vault()

    result = restore("Привет, [ORG_42]!", vault)

    assert "[ORG_42]" in result.text
    assert result.skipped


def test_restore_skips_inside_url() -> None:
    """Внутри ссылки значение не восстанавливается: иначе утечка через URL."""
    vault = _vault()
    vault.add("prep", "org", "Ромашка")

    result = restore("См. https://example.com/[ORG_1]/report", vault)

    assert "[ORG_1]" in result.text
    assert result.restored == 0
    assert any("ссылк" in reason for _, reason in result.skipped)


def test_restore_does_not_recurse() -> None:
    """Подставленное значение не сканируется повторно.

    Если исходное значение само содержит псевдонимоподобный текст, он не
    должен подмениться: это защита от цепочек восстановления.
    """
    vault = _vault()
    vault.add("prep", "org", "[ORG_1] внутри значения")

    result = restore("[ORG_1] готово", vault)

    assert result.text == "[ORG_1] внутри значения готово"
    assert result.restored == 1


def test_secret_is_removed_and_not_restorable() -> None:
    """Секрет удаляется на этапе санитизации и восстановить его нельзя.

    Это осознанное решение: секрет вообще не попадает в vault, поэтому даже
    явное разрешение пользователя не может вернуть его из ответа.
    """
    vault = _vault()
    text = "api_key: super-secret-value-123"

    sanitized = sanitize(text, detect(text), vault, "prep")
    result = restore(sanitized.text, vault)

    assert "super-secret-value-123" not in sanitized.text
    assert "super-secret-value-123" not in result.text
    assert result.restored == 0


def test_secret_restored_when_explicitly_allowed() -> None:
    """Явное разрешение не может восстановить удалённый секрет.

    Проверяем границу: псевдонима у секрета нет, поэтому `restore` оставляет
    маркер удаления — текст остаётся читаемым, значение не возвращается.
    """
    vault = _vault()
    text = "api_key: super-secret-value-123"
    sanitized = sanitize(text, detect(text), vault, "prep")
    placeholder = next(
        entity.placeholder
        for entity in sanitized.entities
        if entity.category == "secret"
    )

    result = restore(
        sanitized.text, vault, allow_secret_placeholders={placeholder}
    )

    assert "super-secret-value-123" not in result.text
    assert REMOVED_MARKER in result.text
