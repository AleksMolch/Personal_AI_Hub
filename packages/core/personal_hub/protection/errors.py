"""Ошибки защищённых режимов.

Стабильные коды нужны, чтобы UI показывал понятное действие (показать preview
заново, переключить режим, повторить позже), а не текст исключения.
"""
from __future__ import annotations


class ProtectionError(Exception):
    """Ошибка подготовки/восстановления защищённого запроса.

    Args:
        code: Стабильный машинный код (`PROTECTION_*`).
        message: Понятное пользователю объяснение.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
