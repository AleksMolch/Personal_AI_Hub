"""Потоковое восстановление ответа модели (ADR-0007, срез 4).

Назначение: показывать пользователю восстановленный текст по мере генерации,
не дожидаясь конца ответа. Псевдонимы `[EMAIL_1]` могут приходить разрезанными
между чанками, поэтому хвост, который ещё может оказаться частью псевдонима,
придерживается до следующего чанка.

Место в архитектуре: вызывается `chat_worker` при подтверждённой подготовке.
Восстановление локальное: наружу ничего не отправляется.

Инварианты:
1. Не восстанавливаем внутри URL: если в буфере есть незакрытый `http://…`,
   держим его до пробела, чтобы `restore` не подставил значение в ссылку.
2. Подставленный текст не сканируется повторно: `restore` заменяет только
   псевдонимы, поэтому рекурсии нет по построению.
3. Хвост, похожий на начало псевдонима (`[`, `[EM…`), не отдаётся, пока
   псевдоним не станет полным.
"""
from __future__ import annotations

import re

from personal_hub.protection.sanitizer import restore
from personal_hub.protection.vault import EntityVault

# Полный псевдоним: [CATEGORY_N].
_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


class StreamingRestorer:
    """Восстанавливает псевдонимы в потоке чанков.

    Args:
        vault: Vault с картой соответствий.

    Attributes:
        restored: Сколько псевдонимов уже восстановлено.
        skipped: Сколько псевдонимов пропущено (неизвестные, внутри ссылок).
    """

    def __init__(self, vault: EntityVault) -> None:
        self.vault = vault
        self.restored = 0
        self.skipped = 0
        self._buffer = ""

    def feed(self, delta: str) -> str:
        """Принимает чанк и возвращает ту его часть, что уже безопасно отдать.

        Args:
            delta: Новый фрагмент текста от модели.

        Returns:
            Восстановленный текст, который можно показать (может быть пустым).
        """
        self._buffer += delta
        cut = self._safe_cut()
        head, self._buffer = self._buffer[:cut], self._buffer[cut:]
        if not head:
            return ""
        result = restore(head, self.vault)
        self.restored += result.restored
        self.skipped += len(result.skipped)
        return result.text

    def flush(self) -> str:
        """Отдаёт оставшийся хвост после завершения потока."""
        tail, self._buffer = self._buffer, ""
        if not tail:
            return ""
        result = restore(tail, self.vault)
        self.restored += result.restored
        self.skipped += len(result.skipped)
        return result.text

    def _safe_cut(self) -> int:
        """Возвращает индекс, до которого текст можно отдавать без риска.

        Держим два вида хвоста: незавершённый псевдоним и незавершённый URL
        (внутри ссылки восстановление запрещено).
        """
        buffer = self._buffer
        cut = len(buffer)

        last_open = buffer.rfind("[")
        if last_open != -1 and not _PLACEHOLDER_RE.fullmatch(buffer[last_open:]):
            # Хвост может оказаться началом псевдонима — придерживаем его.
            cut = min(cut, last_open)

        for token in ("http://", "https://"):
            index = buffer.rfind(token)
            if index != -1 and " " not in buffer[index:]:
                cut = min(cut, index)

        return cut
