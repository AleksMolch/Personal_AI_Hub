"""Тесты digest и репозитория защищённых подготовок (ADR-0007, срез 2).

Unit-часть: канонический digest. Интеграционная часть (в
`tests/integration/test_protection_repository.py`) проверяет хранение,
идемпотентность и отказы.
"""
from __future__ import annotations

from personal_hub.protection.repository import payload_digest


def test_digest_is_stable_regardless_of_key_order() -> None:
    """Один и тот же смысл даёт одинаковый digest при разном порядке ключей."""
    first = payload_digest({"model": "deepseek-flash", "messages": [{"role": "user"}]})
    second = payload_digest({"messages": [{"role": "user"}], "model": "deepseek-flash"})

    assert first == second


def test_digest_changes_with_content() -> None:
    """Изменение содержимого меняет digest: иначе commit пропустил бы правку."""
    first = payload_digest({"text": "привет"})
    second = payload_digest({"text": "привет!"})

    assert first != second


def test_digest_handles_non_json_values() -> None:
    """Decimal и даты не ломают digest: они приводятся к строке."""
    from datetime import datetime, timezone
    from decimal import Decimal

    digest = payload_digest({"price": Decimal("0.15"), "at": datetime.now(timezone.utc)})

    assert len(digest) == 64
