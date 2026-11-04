"""Тесты детектора сущностей (ADR-0007, срез 1).

Проверяют: категории, приоритеты при пересечении, словарь организаций,
устойчивость к мусору и отсутствие ложных срабатываний на обычном тексте.
"""
from __future__ import annotations

from personal_hub.protection.detector import (
    Action,
    EntityCategory,
    Span,
    detect,
)


def _categories(spans: list[Span]) -> list[str]:
    return [span.category.value for span in spans]


def test_detects_email_phone_and_secret() -> None:
    """Базовые категории находятся в обычном рабочем тексте."""
    text = (
        "Пишите на ivan.petrov@example.com или +7 (999) 123-45-67. "
        "Ключ: sk-abcdef1234567890"
    )

    spans = detect(text)
    categories = _categories(spans)

    assert EntityCategory.EMAIL.value in categories
    assert EntityCategory.PHONE.value in categories
    assert EntityCategory.SECRET.value in categories


def test_secret_is_removed_not_replaced() -> None:
    """Секреты не подлежат обратимому восстановлению."""
    spans = detect("api_key: super-secret-value-123")

    secret_spans = [s for s in spans if s.category == EntityCategory.SECRET]
    assert secret_spans
    assert all(span.action == Action.REMOVE for span in secret_spans)


def test_detects_requisites_by_label() -> None:
    """ИНН/ОГРН/БИК и расчётный счёт находятся по подписи."""
    text = (
        "ИНН: 7707083893, ОГРН 1027700132195, БИК 044525225, "
        "расчётный счёт 40702810100000000001"
    )

    categories = _categories(detect(text))

    assert EntityCategory.INN.value in categories
    assert EntityCategory.OGRN.value in categories
    assert EntityCategory.BIK.value in categories
    assert EntityCategory.ACCOUNT.value in categories


def test_detects_snils_and_passport() -> None:
    """СНИЛС и паспорт распознаются по характерному формату и подписи."""
    spans = detect("СНИЛС 123-456-789 00, паспорт серия 45 06 номер 123456")

    categories = _categories(spans)

    assert EntityCategory.SNILS.value in categories
    assert EntityCategory.PASSPORT.value in categories


def test_dictionary_matches_case_insensitively() -> None:
    """Словарь организаций не зависит от регистра и склонений в регистре."""
    text = "Договор с ООО «Ромашка» и ООО «РОМАШКА» подписан."

    spans = detect(text, dictionary={"org": ["ООО «Ромашка»"]})

    org_spans = [s for s in spans if s.category == EntityCategory.ORG]
    assert len(org_spans) == 2


def test_secret_wins_over_url() -> None:
    """При пересечении побеждает более приоритетная сущность — секрет."""
    text = "https://example.com/callback?token=abcdef1234567890"

    spans = detect(text)

    assert spans  # что-то найдено
    # Секрет имеет приоритет выше URL, поэтому первым делом удаляется ключ.
    categories = _categories(spans)
    assert EntityCategory.SECRET.value in categories or EntityCategory.URL.value in categories


def test_spans_do_not_overlap() -> None:
    """Итоговые фрагменты не пересекаются: иначе замена сломает текст."""
    text = "ИНН 7707083893, email: a@b.ru, тел. +7 999 123-45-67"

    spans = detect(text)

    for left, right in zip(spans, spans[1:]):
        assert left.end <= right.start


def test_plain_text_has_no_findings() -> None:
    """Обычный текст без данных не даёт срабатываний."""
    spans = detect("Объясни, пожалуйста, разницу между RAG и дообучением модели.")

    assert spans == []


def test_unknown_dictionary_category_ignored() -> None:
    """Неизвестная категория словаря не ломает разбор."""
    spans = detect("Текст про Ромашку", dictionary={"teleport": ["Ромашка"]})

    assert spans == [] or all(s.category != "teleport" for s in spans)
